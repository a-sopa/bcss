"""MITRE ATT&CK mapping engine for Linux and Cloud attack techniques."""

from dataclasses import dataclass
import re
from typing import Dict, List, Optional


@dataclass
class MitreTechnique:
    """Represents a mapped MITRE ATT&CK technique."""
    technique_id: str
    name: str
    tactic: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    matched_command: str


class MitreAttackMapper:
    """Maps observed honeypot activities to MITRE ATT&CK framework."""

    RULES = [
        # Credential Access
        {
            "id": "T1110.001",
            "name": "Password Guessing / Brute Force",
            "tactic": "Credential Access",
            "severity": "MEDIUM",
            "regex": re.compile(r"(admin123|brute|password|login)", re.I),
            "desc": "Attacker attempted automated or dictionary-based password guessing.",
        },
        {
            "id": "T1552.001",
            "name": "Credentials in Files",
            "tactic": "Credential Access",
            "severity": "CRITICAL",
            "regex": re.compile(r"(shadow|\.aws/credentials|\.env|id_rsa|\.dockercfg|database_url)", re.I),
            "desc": "Attacker searched for or extracted stored credentials from configuration or credential files.",
        },
        # Discovery
        {
            "id": "T1082",
            "name": "System Information Discovery",
            "tactic": "Discovery",
            "severity": "LOW",
            "regex": re.compile(r"^(uname|cat\s+/etc/os-release|cat\s+/etc/issue|hostname|uptime)", re.I),
            "desc": "Attacker gathered detailed information about the operating system and cloud kernel.",
        },
        {
            "id": "T1087.001",
            "name": "Local Account Discovery",
            "tactic": "Discovery",
            "severity": "MEDIUM",
            "regex": re.compile(r"^(whoami|id|cat\s+/etc/passwd|w|who|last)", re.I),
            "desc": "Attacker enumerated usernames, user IDs, and group permissions.",
        },
        {
            "id": "T1046",
            "name": "Network Service Discovery",
            "tactic": "Discovery",
            "severity": "MEDIUM",
            "regex": re.compile(r"^(netstat|ss|ifconfig|ip\s+a|arp|route)", re.I),
            "desc": "Attacker attempted to discover listening services and network interfaces on the cloud VPC.",
        },
        {
            "id": "T1083",
            "name": "File and Directory Discovery",
            "tactic": "Discovery",
            "severity": "LOW",
            "regex": re.compile(r"^(ls|find|dir|pwd|tree)", re.I),
            "desc": "Attacker enumerated directories and file structures looking for sensitive assets.",
        },
        {
            "id": "T1057",
            "name": "Process Discovery",
            "tactic": "Discovery",
            "severity": "LOW",
            "regex": re.compile(r"^(ps|top|htop|pstree)", re.I),
            "desc": "Attacker inspected running system and container processes.",
        },
        # Command and Control / Tool Transfer
        {
            "id": "T1105",
            "name": "Ingress Tool Transfer",
            "tactic": "Command and Control",
            "severity": "HIGH",
            "regex": re.compile(r"(curl|wget|scp|ftp|tftp|python.*urllib|nc\s+.*-e)", re.I),
            "desc": "Attacker transferred tools, payloads, or malware droppers into the cloud environment.",
        },
        # Privilege Escalation
        {
            "id": "T1548.003",
            "name": "Sudo and Sudo Caching",
            "tactic": "Privilege Escalation",
            "severity": "HIGH",
            "regex": re.compile(r"^(sudo|su\s+|su$)", re.I),
            "desc": "Attacker executed commands with elevated root privileges or attempted privilege escalation.",
        },
        # Defense Evasion
        {
            "id": "T1070.004",
            "name": "File Deletion",
            "tactic": "Defense Evasion",
            "severity": "MEDIUM",
            "regex": re.compile(r"^(rm\s+|rmdir|unlink|history\s+-c)", re.I),
            "desc": "Attacker deleted evidence, payload files, or bash history to evade detection.",
        },
        # Impact
        {
            "id": "T1496",
            "name": "Resource Hijacking",
            "tactic": "Impact",
            "severity": "CRITICAL",
            "regex": re.compile(r"(xmrig|stratum\+tcp|monero|minerd|cryptonight|cpuminer)", re.I),
            "desc": "Attacker attempted to hijack cloud compute and CPU resources for illicit cryptocurrency mining.",
        },
    ]

    def map_commands(self, commands: List[Dict]) -> List[MitreTechnique]:
        """Map a list of executed commands to MITRE techniques."""
        findings: List[MitreTechnique] = []
        seen = set()

        for c in commands:
            cmd = c.get("command", "")
            for rule in self.RULES:
                if rule["regex"].search(cmd):
                    key = (rule["id"], rule["name"])
                    if key not in seen:
                        seen.add(key)
                        findings.append(
                            MitreTechnique(
                                technique_id=rule["id"],
                                name=rule["name"],
                                tactic=rule["tactic"],
                                severity=rule["severity"],
                                description=rule["desc"],
                                matched_command=cmd,
                            )
                        )
        return findings

    def map_auth(self, num_attempts: int) -> Optional[MitreTechnique]:
        """Map authentication brute force activity."""
        if num_attempts >= 2:
            return MitreTechnique(
                technique_id="T1110.001",
                name="Password Guessing / Brute Force",
                tactic="Credential Access",
                severity="HIGH" if num_attempts >= 5 else "MEDIUM",
                description=f"Observed {num_attempts} password attempts in a single connection.",
                matched_command=f"Brute-force loop ({num_attempts} attempts)",
            )
        return None


MITRE_MAPPER = MitreAttackMapper()
