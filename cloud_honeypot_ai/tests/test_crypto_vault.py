"""Unit tests for forensic evidence cryptographic vault."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cloud_honeypot_ai.crypto.vault import ForensicCryptoVault


class TestCryptoVault(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.vault = ForensicCryptoVault(vault_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_seal_and_decrypt_session(self):
        sample_session = {
            "session_id": "test-session-1234",
            "remote_ip": "185.220.101.5",
            "protocol": "SSH",
            "auth_attempts": [{"username": "root", "password": "admin123", "success": True}],
            "commands": [{"command": "whoami", "output": "root\n"}],
        }

        block = self.vault.seal_session(sample_session)
        self.assertEqual(block.block_index, 1)
        self.assertEqual(block.session_id, "test-session-1234")
        self.assertEqual(len(block.block_hash), 64)
        self.assertEqual(len(block.hmac_signature), 64)

        # Decrypt session
        decrypted = self.vault.read_decrypted_session("test-session-1234")
        self.assertIsNotNone(decrypted)
        self.assertEqual(decrypted["remote_ip"], "185.220.101.5")
        self.assertEqual(decrypted["auth_attempts"][0]["password"], "admin123")

    def test_blockchain_hash_chaining(self):
        s1 = {"session_id": "s1", "ip": "1.1.1.1"}
        s2 = {"session_id": "s2", "ip": "2.2.2.2"}
        s3 = {"session_id": "s3", "ip": "3.3.3.3"}

        b1 = self.vault.seal_session(s1)
        b2 = self.vault.seal_session(s2)
        b3 = self.vault.seal_session(s3)

        self.assertEqual(b1.previous_hash, "0" * 64)
        self.assertEqual(b2.previous_hash, b1.block_hash)
        self.assertEqual(b3.previous_hash, b2.block_hash)

        valid, msgs = self.vault.verify_vault_integrity()
        self.assertTrue(valid)
        self.assertIn("Successfully verified 3 blocks", msgs[0])

    def test_tamper_detection(self):
        s = {"session_id": "s-tamper", "ip": "103.203.57.12"}
        self.vault.seal_session(s)

        # Alter the ledger file on disk
        lines = self.vault.ledger_file.read_text().splitlines()
        first_block = json.loads(lines[0])
        first_block["session_id"] = "falsified-session-id"  # Attacker attempts to modify evidence
        self.vault.ledger_file.write_text(json.dumps(first_block) + "\n")

        # Verify integrity should now catch tampering
        valid, errors = self.vault.verify_vault_integrity()
        self.assertFalse(valid)
        self.assertTrue(any("tampering detected" in err or "HMAC" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
