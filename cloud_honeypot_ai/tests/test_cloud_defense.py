"""Unit tests for automated cloud defense rule generation and efficiency optimization."""

import unittest

from cloud_honeypot_ai.ai.cloud_defense import CloudDefenseOptimizer


class TestCloudDefense(unittest.TestCase):

    def setUp(self):
        self.defense = CloudDefenseOptimizer()

    def test_add_malicious_ip_filtering(self):
        # Localhost / private IPs should be ignored
        self.defense.add_malicious_ip("127.0.0.1")
        self.defense.add_malicious_ip("10.0.1.42")
        self.assertEqual(len(self.defense.blocked_ips), 0)

        # Public malicious IPs should be added
        self.defense.add_malicious_ip("194.26.29.42")
        self.defense.add_malicious_ip("45.154.255.88")
        self.assertEqual(len(self.defense.blocked_ips), 2)

    def test_efficiency_metrics_calculation(self):
        self.defense.add_malicious_ip("194.26.29.42")
        metrics = self.defense.calculate_efficiency_metrics()

        self.assertEqual(metrics.blocked_ips_count, 1)
        self.assertGreater(metrics.estimated_attacks_blocked_monthly, 100000)
        self.assertGreater(metrics.bandwidth_saved_gb, 0.5)
        self.assertGreater(metrics.total_estimated_monthly_savings_usd, 5.0)

    def test_generate_defense_rules(self):
        self.defense.add_malicious_ip("194.26.29.42")
        self.defense.add_malicious_ip("185.220.101.5")
        ruleset = self.defense.generate_defense_rules()

        self.assertEqual(len(ruleset.aws_nacl_cli), 2)
        self.assertIn("aws ec2 create-network-acl-entry", ruleset.aws_nacl_cli[0])
        self.assertIn("deny", ruleset.aws_nacl_cli[0])

        self.assertEqual(len(ruleset.aws_sg_cli), 2)
        self.assertIn("aws ec2 revoke-security-group-ingress", ruleset.aws_sg_cli[0])

        self.assertEqual(len(ruleset.linux_iptables), 2)
        self.assertIn("iptables -I INPUT -s", ruleset.linux_iptables[0])
        self.assertIn("DROP", ruleset.linux_iptables[0])

        self.assertEqual(len(ruleset.cloudflare_waf_api), 2)
        self.assertEqual(ruleset.cloudflare_waf_api[0]["mode"], "block")

        self.assertIn("resource \"aws_network_acl_rule\"", ruleset.terraform_snippet)


if __name__ == "__main__":
    unittest.main()
