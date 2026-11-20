"""Automated Cloud Resource Defense and Efficiency Optimization Engine."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from cloud_honeypot_ai.config import CONFIG

logger = logging.getLogger("honeypot.ai.defense")


@dataclass
class CloudEfficiencyMetrics:
    """Quantifies cloud compute, bandwidth, and cost savings achieved by early packet drops."""
    blocked_ips_count: int
    estimated_attacks_blocked_monthly: int
    bandwidth_saved_gb: float
    cpu_cycles_saved_mhz: float
    avoided_cloudwatch_cost_usd: float
    total_estimated_monthly_savings_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocked_ips_count": self.blocked_ips_count,
            "estimated_attacks_blocked_monthly": self.estimated_attacks_blocked_monthly,
            "bandwidth_saved_gb": round(self.bandwidth_saved_gb, 2),
            "cpu_cycles_saved_mhz": round(self.cpu_cycles_saved_mhz, 2),
            "avoided_cloudwatch_cost_usd": round(self.avoided_cloudwatch_cost_usd, 2),
            "total_estimated_monthly_savings_usd": round(self.total_estimated_monthly_savings_usd, 2),
        }


@dataclass
class CloudFirewallRuleSet:
    """Generated firewall defense rules across cloud platforms."""
    generated_at: str
    target_ips: List[str]
    aws_nacl_cli: List[str]
    aws_sg_cli: List[str]
    linux_iptables: List[str]
    cloudflare_waf_api: List[Dict[str, Any]]
    terraform_snippet: str
    efficiency_metrics: CloudEfficiencyMetrics


class CloudDefenseOptimizer:
    """Generates automated perimeter defense rules to optimize cloud resource efficiency."""

    def __init__(self, rules_dir: Optional[Path] = None):
        self.rules_dir = rules_dir or CONFIG.rules_dir
        self.blocked_ips: Set[str] = set()

    def add_malicious_ip(self, ip: str) -> None:
        """Register an attacking IP to be blocked."""
        # Avoid blocking private/localhost
        if ip in ("127.0.0.1", "localhost", "::1") or ip.startswith("10.") or ip.startswith("192.168."):
            return
        self.blocked_ips.add(ip)

    def calculate_efficiency_metrics(self) -> CloudEfficiencyMetrics:
        """Calculate cloud compute and bill reduction metrics.

        Standard cloud cost model (AWS/GCP average):
        - A typical brute-force bot sends ~12,000 requests/day to a target IP.
        - Bandwidth per attack attempt ~ 2 KB headers/payload = 24 MB/day per bot.
        - CPU processing: 100 ssh/tls handshakes consume ~ 2% of a vCPU continuously.
        - CloudWatch logs: $0.50 per GB ingested.
        - Network Data Transfer: $0.09 per GB.
        """
        num_ips = max(len(self.blocked_ips), 1)

        # Attacks blocked per month (approx 360,000 requests per rogue IP per month)
        attacks_monthly = num_ips * 360000

        # Data transfer saved in GB
        gb_saved = (attacks_monthly * 2.5) / (1024 * 1024)  # 2.5 KB per request

        # CPU processing saved (in MHz equivalent)
        cpu_saved = num_ips * 150.0

        # Avoided CloudWatch log ingestion ($0.50 / GB)
        cloudwatch_savings = gb_saved * 0.50

        # Avoided network egress + avoided EC2 compute waste ($0.09/GB + compute savings)
        network_savings = gb_saved * 0.09
        compute_savings = num_ips * 14.50  # estimated avoided EC2 compute overhead

        total_savings = cloudwatch_savings + network_savings + compute_savings

        return CloudEfficiencyMetrics(
            blocked_ips_count=len(self.blocked_ips),
            estimated_attacks_blocked_monthly=attacks_monthly,
            bandwidth_saved_gb=gb_saved,
            cpu_cycles_saved_mhz=cpu_saved,
            avoided_cloudwatch_cost_usd=cloudwatch_savings,
            total_estimated_monthly_savings_usd=total_savings,
        )

    def generate_defense_rules(self) -> CloudFirewallRuleSet:
        """Synthesize cloud defense rules for AWS NACL, Security Groups, iptables, and Cloudflare."""
        now_iso = datetime.now(timezone.utc).isoformat()
        ip_list = sorted(list(self.blocked_ips))

        # 1. AWS Network ACL (NACL) - Stateless packet drop before reaching EC2
        aws_nacl_cmds = []
        rule_num = 100
        for ip in ip_list:
            aws_nacl_cmds.append(
                f"aws ec2 create-network-acl-entry --network-acl-id acl-01a2b3c4d5e6f7 --rule-number {rule_num} "
                f"--protocol -1 --rule-action deny --cidr-block {ip}/32 --ingress"
            )
            rule_num += 1

        # 2. AWS Security Group Ingress Revocation
        aws_sg_cmds = []
        for ip in ip_list:
            aws_sg_cmds.append(
                f"aws ec2 revoke-security-group-ingress --group-id sg-0123456789abcdef0 "
                f"--protocol tcp --port 22 --cidr {ip}/32"
            )

        # 3. Linux iptables / nftables commands
        iptables_cmds = [
            f"iptables -I INPUT -s {ip} -j DROP" for ip in ip_list
        ]

        # 4. Cloudflare WAF Access Rules
        cf_rules = [
            {
                "mode": "block",
                "configuration": {"target": "ip", "value": ip},
                "notes": "Blocked by Cloud Honeypot AI Shield (Brute Force Attacker)",
            }
            for ip in ip_list
        ]

        # 5. Terraform Infrastructure-as-Code snippet
        tf_cidrs = json.dumps([f"{ip}/32" for ip in ip_list], indent=4)
        terraform_snippet = (
            "# Automated Cloud Honeypot AI Perimeter Defense\n"
            "resource \"aws_network_acl_rule\" \"honeypot_botnet_drop\" {\n"
            "  network_acl_id = var.vpc_main_nacl_id\n"
            "  rule_number    = 100\n"
            "  egress         = false\n"
            "  protocol       = \"-1\"\n"
            "  rule_action    = \"deny\"\n"
            f"  cidr_block     = \"{ip_list[0] if ip_list else '0.0.0.0'}/32\"\n"
            "}\n"
        )

        metrics = self.calculate_efficiency_metrics()

        ruleset = CloudFirewallRuleSet(
            generated_at=now_iso,
            target_ips=ip_list,
            aws_nacl_cli=aws_nacl_cmds,
            aws_sg_cli=aws_sg_cmds,
            linux_iptables=iptables_cmds,
            cloudflare_waf_api=cf_rules,
            terraform_snippet=terraform_snippet,
            efficiency_metrics=metrics,
        )

        # Save to disk
        self._save_ruleset(ruleset)
        return ruleset

    def _save_ruleset(self, ruleset: CloudFirewallRuleSet) -> None:
        if not self.rules_dir:
            return
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.rules_dir / "latest_cloud_defense_rules.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": ruleset.generated_at,
                    "target_ips": ruleset.target_ips,
                    "aws_nacl_cli": ruleset.aws_nacl_cli,
                    "aws_sg_cli": ruleset.aws_sg_cli,
                    "linux_iptables": ruleset.linux_iptables,
                    "cloudflare_waf_api": ruleset.cloudflare_waf_api,
                    "terraform": ruleset.terraform_snippet,
                    "efficiency_metrics": ruleset.efficiency_metrics.to_dict(),
                },
                f,
                indent=2,
            )


# Singleton optimizer instance
CLOUD_DEFENSE = CloudDefenseOptimizer()
