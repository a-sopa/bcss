"""Unit tests for cloud cryptographic posture auditor and canary crypto generator."""

import unittest

from cloud_honeypot_ai.crypto.canary_keys import CanaryCryptoGenerator
from cloud_honeypot_ai.crypto.posture_auditor import CloudCryptoAuditor


class TestCryptoAuditor(unittest.TestCase):

    def setUp(self):
        self.auditor = CloudCryptoAuditor()
        self.canary_gen = CanaryCryptoGenerator()

    def test_ssh_cipher_audit(self):
        findings = self.auditor.audit_ssh_ciphers(
            ciphers=["3des-cbc", "aes128-cbc", "chacha20-poly1305@openssh.com"],
            kex_algorithms=["diffie-hellman-group1-sha1", "x25519mlkem768"],
        )
        algorithms_flagged = {f.algorithm for f in findings}

        self.assertIn("3des-cbc", algorithms_flagged)
        self.assertIn("aes128-cbc", algorithms_flagged)
        self.assertIn("diffie-hellman-group1-sha1", algorithms_flagged)
        self.assertIn("x25519mlkem768", algorithms_flagged)

        # Check statuses
        status_map = {f.algorithm: f.status for f in findings}
        self.assertEqual(status_map["3des-cbc"], "DEPRECATED")
        self.assertEqual(status_map["aes128-cbc"], "WEAK")
        self.assertEqual(status_map["x25519mlkem768"], "QUANTUM_SAFE")

    def test_tls_policy_audit(self):
        findings = self.auditor.audit_tls_policy(
            protocol_versions=["TLSv1.0", "TLSv1.2", "TLSv1.3"],
            ciphers=["ECDHE-RSA-AES128-GCM-SHA256", "AES128-SHA"],
        )
        deprecated = [f for f in findings if f.status == "DEPRECATED"]
        self.assertTrue(any(f.algorithm == "TLSv1.0" for f in deprecated))

    def test_environment_evaluation_and_grading(self):
        # A flawed environment with weak ciphers
        report = self.auditor.evaluate_environment(
            ssh_ciphers=["3des-cbc"],
            ssh_kex=["diffie-hellman-group1-sha1"],
            tls_protocols=["TLSv1.0"],
        )
        self.assertLess(report.security_score, 70)
        self.assertIn(report.grade, ("C", "D", "F"))

        # A modern quantum-safe hardened environment
        hardened_report = self.auditor.evaluate_environment(
            ssh_ciphers=["chacha20-poly1305@openssh.com"],
            ssh_kex=["x25519mlkem768"],
            tls_protocols=["TLSv1.3"],
            tls_ciphers=["TLS_AES_256_GCM_SHA384"],
        )
        self.assertGreaterEqual(hardened_report.security_score, 90)
        self.assertEqual(hardened_report.grade, "A")
        self.assertGreater(hardened_report.pqc_readiness_score, 40)

    def test_canary_crypto_generation(self):
        bundle = self.canary_gen.generate_bundle("hackathon_canary_01")
        self.assertIn("BEGIN RSA PRIVATE KEY", bundle.rsa_private_key_pem)
        self.assertIn("BEGIN PUBLIC KEY", bundle.rsa_public_key_pem)
        self.assertIn("arn:aws:kms:", bundle.fake_kms_arn)

        self.assertTrue(self.canary_gen.is_canary(bundle.fake_kms_arn))
        self.assertFalse(self.canary_gen.is_canary("standard_random_string_xyz"))


if __name__ == "__main__":
    unittest.main()
