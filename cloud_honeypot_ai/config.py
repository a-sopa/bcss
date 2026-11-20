"""Configuration module for Cloud Honeypot AI & Defense Shield."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set


@dataclass
class HoneypotConfig:
    """Core honeypot and environment configuration."""

    # Server Bind Settings
    host: str = "0.0.0.0"
    ssh_port: int = 2222
    tcp_port: int = 2323  # Telnet / raw TCP decoy
    http_port: int = 8080  # Web / Cloud API decoy
    dashboard_port: int = 8888  # Web UI Dashboard

    # Honey Credentials: easy "half-open" passwords for attackers to guess
    weak_passwords: Set[str] = field(
        default_factory=lambda: {
            "admin123",
            "admin",
            "root",
            "toor",
            "123456",
            "password",
            "ubuntu",
            "guest",
            "cloudadmin",
            "picoas2026",
        }
    )

    allowed_usernames: Set[str] = field(
        default_factory=lambda: {
            "root",
            "admin",
            "ubuntu",
            "ec2-user",
            "deploy",
            "support",
        }
    )

    # Simulated Cloud Host Environment
    hostname: str = "ip-10-0-1-42.ec2.internal"
    os_name: str = "Ubuntu 22.04.4 LTS (Jammy Jellyfish)"
    kernel_release: str = "5.15.0-101-generic"
    architecture: str = "x86_64"
    cloud_provider: str = "AWS Cloud (EC2 Ireland eu-west-1)"
    prompt_template: str = "{username}@{hostname}:{cwd}$ "

    # Data & Log Directories
    base_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent
    )
    logs_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "data" / "logs"
    )
    vault_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "data" / "vault"
    )
    rules_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "data" / "firewall_rules"
    )

    # Canary Tokens (Honey-Tokens for detecting cloud credential exfiltration)
    canary_aws_key_id: str = "HONEY_CANARY_AWS_KEY_DEMO_01"
    canary_aws_secret: str = "HONEY_CANARY_AWS_SECRET_PASS_TOKEN_DEMO_99"
    canary_db_connection: str = "postgresql://dbadmin:picoas_canary_pass@prod-db.internal:5432/customers"

    def __post_init__(self):
        """Ensure directories exist."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.rules_dir.mkdir(parents=True, exist_ok=True)


# Default shared singleton config
CONFIG = HoneypotConfig()
