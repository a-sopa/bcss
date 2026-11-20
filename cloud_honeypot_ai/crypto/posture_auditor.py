"""Cloud Cryptographic Posture Auditor.

Audits cryptographic algorithms, key lengths, TLS/SSH ciphers, AWS KMS keys,
and assesses Post-Quantum Cryptography (PQC) transition readiness.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional


@dataclass
class CryptoFinding:
    """Individual cryptographic vulnerability or assessment finding."""
    component: str  # SSH, TLS, KMS, CERTIFICATE
    target: str
    algorithm: str
    status: str  # DEPRECATED, WEAK, ACCEPTABLE, QUANTUM_SAFE
    severity: str  # INFO, LOW, MEDIUM, HIGH, CRITICAL
    description: str
    recommendation: str
    standard_reference: str


@dataclass
class CryptoAuditReport:
    """Consolidated cryptographic posture assessment report."""
    audited_at: str
    security_score: int  # 0 to 100
    grade: str  # A, B, C, D, F
    total_findings: int
    findings: List[CryptoFinding]
    pqc_readiness_score: int  # 0 to 100
    executive_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audited_at": self.audited_at,
            "security_score": self.security_score,
            "grade": self.grade,
            "total_findings": self.total_findings,
            "findings": [asdict(f) for f in self.findings],
            "pqc_readiness_score": self.pqc_readiness_score,
            "executive_summary": self.executive_summary,
        }


class CloudCryptoAuditor:
    """Evaluates cloud infrastructure cryptographic posture against NIST and RFC guidelines."""

    DEPRECATED_CIPHERS = {"3DES", "DES", "RC4", "BLOWFISH", "CAST128", "ARCFOUR", "IDEA"}
    WEAK_HASHES = {"MD5", "SHA1"}
    MODERN_PQC_HYBRIDS = {
        "X25519MLKEM768",
        "SNTRUP761X25519",
        "MLKEM768",
        "MLKEM1024",
        "MLDSA",
        "SLHDSA",
    }

    def audit_ssh_ciphers(self, ciphers: List[str], kex_algorithms: List[str]) -> List[CryptoFinding]:
        """Audit SSH server cipher and key exchange suites."""
        findings = []

        for cipher in ciphers:
            c_upper = cipher.upper()
            if any(dep in c_upper for dep in self.DEPRECATED_CIPHERS):
                findings.append(
                    CryptoFinding(
                        component="SSH",
                        target="sshd_config (Ciphers)",
                        algorithm=cipher,
                        status="DEPRECATED",
                        severity="CRITICAL",
                        description=f"Cipher '{cipher}' is cryptographically broken and vulnerable to Sweet32/collision attacks.",
                        recommendation="Remove and enforce 'chacha20-poly1305@openssh.com,aes256-gcm@openssh.com'.",
                        standard_reference="NIST SP 800-131A Rev 2 / RFC 8731",
                    )
                )
            elif "CBC" in c_upper:
                findings.append(
                    CryptoFinding(
                        component="SSH",
                        target="sshd_config (Ciphers)",
                        algorithm=cipher,
                        status="WEAK",
                        severity="MEDIUM",
                        description=f"Cipher '{cipher}' uses CBC mode susceptible to padding oracle attacks.",
                        recommendation="Migrate to authenticated encryption (AEAD) using AES-GCM or ChaCha20-Poly1305.",
                        standard_reference="RFC 5647 / NIST SP 800-38D",
                    )
                )

        for kex in kex_algorithms:
            k_upper = kex.upper()
            if "SHA1" in k_upper or "GROUP1-" in k_upper:
                findings.append(
                    CryptoFinding(
                        component="SSH",
                        target="sshd_config (KexAlgorithms)",
                        algorithm=kex,
                        status="DEPRECATED",
                        severity="HIGH",
                        description=f"Key exchange '{kex}' relies on SHA-1 or weak Diffie-Hellman 1024-bit primes.",
                        recommendation="Replace with 'curve25519-sha256,sntrup761x25519-sha512@openssh.com'.",
                        standard_reference="NIST SP 800-131A / RFC 8268",
                    )
                )
            elif any(pqc in k_upper for pqc in self.MODERN_PQC_HYBRIDS):
                findings.append(
                    CryptoFinding(
                        component="SSH",
                        target="sshd_config (KexAlgorithms)",
                        algorithm=kex,
                        status="QUANTUM_SAFE",
                        severity="INFO",
                        description=f"Key exchange '{kex}' implements post-quantum hybrid protection against future quantum decryption.",
                        recommendation="Maintain as preferred modern standard.",
                        standard_reference="NIST FIPS 203 (ML-KEM) / OpenSSH 9+",
                    )
                )

        return findings

    def audit_tls_policy(self, protocol_versions: List[str], ciphers: List[str]) -> List[CryptoFinding]:
        """Audit cloud load balancer (ALB/NLB) TLS policies."""
        findings = []

        for proto in protocol_versions:
            p_clean = proto.upper().replace("_", ".").replace(" ", "").replace("-", "")
            if any(legacy in p_clean for legacy in ("SSLV2", "SSLV3", "SSL2", "SSL3", "TLS1.0", "TLSV1.0", "TLS1.1", "TLSV1.1")):
                findings.append(
                    CryptoFinding(
                        component="TLS",
                        target="Cloud Load Balancer Listener",
                        algorithm=proto,
                        status="DEPRECATED",
                        severity="HIGH",
                        description=f"Protocol '{proto}' is officially deprecated due to POODLE, BEAST, and weak MACs.",
                        recommendation="Disable legacy TLS versions; enforce TLS 1.2 minimum and enable TLS 1.3.",
                        standard_reference="RFC 8996 / NIST SP 800-52 Rev 2",
                    )
                )

        for cipher in ciphers:
            c_upper = cipher.upper()
            if any(h in c_upper for h in self.WEAK_HASHES):
                findings.append(
                    CryptoFinding(
                        component="TLS",
                        target="Cloud Load Balancer Cipher Suite",
                        algorithm=cipher,
                        status="DEPRECATED",
                        severity="HIGH",
                        description=f"Cipher '{cipher}' uses collision-prone hash algorithm.",
                        recommendation="Upgrade to SHA-256 or SHA-384 suites.",
                        standard_reference="RFC 7540",
                    )
                )

        return findings

    def audit_kms_keys(self, kms_inventory: List[Dict[str, Any]]) -> List[CryptoFinding]:
        """Audit AWS KMS key configurations and rotation policies."""
        findings = []
        for key in kms_inventory:
            key_id = key.get("KeyId", "unknown")
            spec = key.get("KeySpec", "SYMMETRIC_DEFAULT")
            rotation = key.get("KeyRotationEnabled", False)

            if not rotation and spec == "SYMMETRIC_DEFAULT":
                findings.append(
                    CryptoFinding(
                        component="KMS",
                        target=f"AWS KMS Key ({key_id})",
                        algorithm=spec,
                        status="WEAK",
                        severity="MEDIUM",
                        description=f"Key {key_id} has automatic annual key rotation disabled.",
                        recommendation="Enable automatic KMS key rotation to limit ciphertext exposure.",
                        standard_reference="AWS Security Best Practices / CIS AWS Benchmark 3.8",
                    )
                )

            if "RSA_2048" in spec:
                findings.append(
                    CryptoFinding(
                        component="KMS",
                        target=f"AWS KMS Asymmetric Key ({key_id})",
                        algorithm=spec,
                        status="ACCEPTABLE",
                        severity="LOW",
                        description="RSA 2048 provides ~112 bits of security and will require migration before 2030.",
                        recommendation="Plan transition to RSA 4096, ECC NIST P-384, or NIST PQC algorithms.",
                        standard_reference="NIST SP 800-57 Part 1",
                    )
                )
        return findings

    def evaluate_environment(
        self,
        ssh_ciphers: Optional[List[str]] = None,
        ssh_kex: Optional[List[str]] = None,
        tls_protocols: Optional[List[str]] = None,
        tls_ciphers: Optional[List[str]] = None,
        kms_keys: Optional[List[Dict[str, Any]]] = None,
    ) -> CryptoAuditReport:
        """Run consolidated audit and compute security score."""
        findings: List[CryptoFinding] = []

        if ssh_ciphers or ssh_kex:
            findings.extend(self.audit_ssh_ciphers(ssh_ciphers or [], ssh_kex or []))
        if tls_protocols or tls_ciphers:
            findings.extend(self.audit_tls_policy(tls_protocols or [], tls_ciphers or []))
        if kms_keys:
            findings.extend(self.audit_kms_keys(kms_keys))

        # Compute Security Score (100 base)
        score = 100
        for f in findings:
            if f.severity == "CRITICAL":
                score -= 30
            elif f.severity == "HIGH":
                score -= 15
            elif f.severity == "MEDIUM":
                score -= 8
            elif f.severity == "LOW":
                score -= 3

        score = max(min(score, 100), 0)

        # Grade
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 65:
            grade = "C"
        elif score >= 50:
            grade = "D"
        else:
            grade = "F"

        # PQC Readiness Score
        pqc_hits = sum(1 for f in findings if f.status == "QUANTUM_SAFE")
        pqc_readiness = min(pqc_hits * 40 + 20, 100)

        summary = (
            f"Cryptographic posture audit completed with score {score}/100 (Grade {grade}). "
            f"Identified {len(findings)} findings ({sum(1 for f in findings if f.severity in ('CRITICAL', 'HIGH'))} high/critical). "
            f"Post-Quantum Readiness is rated at {pqc_readiness}%."
        )

        return CryptoAuditReport(
            audited_at=datetime.now(timezone.utc).isoformat(),
            security_score=score,
            grade=grade,
            total_findings=len(findings),
            findings=findings,
            pqc_readiness_score=pqc_readiness,
            executive_summary=summary,
        )


CRYPTO_AUDITOR = CloudCryptoAuditor()
