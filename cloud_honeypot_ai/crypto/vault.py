"""Forensic Evidence Cryptographic Vault.

Provides AES-256-GCM authenticated encryption, SHA-256 blockchain hash chaining,
and HMAC integrity verification for honeypot incident logs.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cloud_honeypot_ai.config import CONFIG

logger = logging.getLogger("honeypot.crypto.vault")


@dataclass
class VaultBlock:
    """A sealed, tamper-evident block in the forensic cryptographic ledger."""
    block_index: int
    timestamp: str
    session_id: str
    previous_hash: str
    block_hash: str
    hmac_signature: str
    encrypted_payload_hex: str
    nonce_hex: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "previous_hash": self.previous_hash,
            "block_hash": self.block_hash,
            "hmac_signature": self.hmac_signature,
            "encrypted_payload_hex": self.encrypted_payload_hex,
            "nonce_hex": self.nonce_hex,
        }


class ForensicCryptoVault:
    """Tamper-proof evidence vault using AES-256-GCM and SHA-256 chaining."""

    def __init__(
        self,
        vault_dir: Optional[Path] = None,
        master_key: Optional[bytes] = None,
        hmac_key: Optional[bytes] = None,
    ):
        self.vault_dir = vault_dir or CONFIG.vault_dir
        self.vault_dir.mkdir(parents=True, exist_ok=True)

        # 256-bit AES-GCM Key (32 bytes)
        self.aes_key = master_key or self._load_or_generate_key("vault_aes256.key", 32)
        # 256-bit HMAC Key (32 bytes)
        self.hmac_key = hmac_key or self._load_or_generate_key("vault_hmac.key", 32)

        self.ledger_file = self.vault_dir / "evidence_ledger.jsonl"
        self._last_block_hash = "0" * 64
        self._block_count = 0
        self._initialize_ledger()

    def _load_or_generate_key(self, filename: str, length: int) -> bytes:
        key_path = self.vault_dir / filename
        if key_path.exists():
            return key_path.read_bytes()
        new_key = os.urandom(length)
        key_path.write_bytes(new_key)
        # Secure file permissions (rw-------)
        try:
            os.chmod(key_path, 0o600)
        except Exception:
            pass
        return new_key

    def _initialize_ledger(self) -> None:
        """Read existing blocks to restore hash chain continuity."""
        if not self.ledger_file.exists():
            return
        with open(self.ledger_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._last_block_hash = data.get("block_hash", self._last_block_hash)
                    self._block_count += 1
                except Exception:
                    pass

    def seal_session(self, session_dict: Dict[str, Any]) -> VaultBlock:
        """Encrypt session evidence with AES-256-GCM and append to hash chain."""
        plaintext = json.dumps(session_dict, sort_keys=True).encode("utf-8")
        session_id = session_dict.get("session_id", "unknown")
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. AES-256-GCM Encryption with 96-bit unique nonce
        aesgcm = AESGCM(self.aes_key)
        nonce = os.urandom(12)  # 96 bits standard GCM nonce
        aad = session_id.encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)

        # 2. SHA-256 Blockchain Hash Chaining
        block_idx = self._block_count + 1
        prev_hash = self._last_block_hash
        block_content = f"{block_idx}:{now_iso}:{session_id}:{prev_hash}:{ciphertext.hex()}".encode("utf-8")
        block_hash = hashlib.sha256(block_content).hexdigest()

        # 3. HMAC-SHA256 Digital Signature
        sig = hmac.new(self.hmac_key, block_hash.encode("utf-8"), hashlib.sha256).hexdigest()

        block = VaultBlock(
            block_index=block_idx,
            timestamp=now_iso,
            session_id=session_id,
            previous_hash=prev_hash,
            block_hash=block_hash,
            hmac_signature=sig,
            encrypted_payload_hex=ciphertext.hex(),
            nonce_hex=nonce.hex(),
        )

        # Append to persistent ledger
        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(block.to_dict()) + "\n")

        self._last_block_hash = block_hash
        self._block_count += 1
        return block

    def verify_vault_integrity(self) -> Tuple[bool, List[str]]:
        """Verify complete cryptographic chain and HMAC signatures."""
        if not self.ledger_file.exists():
            return True, ["Ledger is empty."]

        errors = []
        expected_prev = "0" * 64
        idx = 0

        with open(self.ledger_file, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                idx += 1
                try:
                    data = json.loads(line)
                    # Check previous hash
                    if data["previous_hash"] != expected_prev:
                        errors.append(f"Block #{idx} (line {line_no}) broken hash chain link.")

                    # Recompute block hash
                    ciphertext_bytes = bytes.fromhex(data["encrypted_payload_hex"])
                    content = f"{data['block_index']}:{data['timestamp']}:{data['session_id']}:{data['previous_hash']}:{ciphertext_bytes.hex()}".encode("utf-8")
                    computed_hash = hashlib.sha256(content).hexdigest()
                    if computed_hash != data["block_hash"]:
                        errors.append(f"Block #{idx} (line {line_no}) hash mismatch - tampering detected!")

                    # Verify HMAC signature
                    computed_sig = hmac.new(self.hmac_key, computed_hash.encode("utf-8"), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(computed_sig, data["hmac_signature"]):
                        errors.append(f"Block #{idx} invalid HMAC signature - key or content altered!")

                    expected_prev = data["block_hash"]
                except Exception as e:
                    errors.append(f"Malformed block at line {line_no}: {e}")

        is_valid = len(errors) == 0
        return is_valid, errors or [f"Successfully verified {idx} blocks. Cryptographic evidence intact."]

    def read_decrypted_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Find and decrypt a session from the vault."""
        if not self.ledger_file.exists():
            return None

        aesgcm = AESGCM(self.aes_key)
        with open(self.ledger_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("session_id") == session_id:
                    ciphertext = bytes.fromhex(data["encrypted_payload_hex"])
                    nonce = bytes.fromhex(data["nonce_hex"])
                    aad = session_id.encode("utf-8")
                    plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
                    return json.loads(plaintext.decode("utf-8"))
        return None


# Global singleton instance
CRYPTO_VAULT = ForensicCryptoVault()
