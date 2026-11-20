"""Configuration module for Cloud Honeypot AI & Defense Shield.

Every setting can be overridden from the environment (see ``HoneypotConfig.from_env``).
Importing this module has no side effects: directories are created by ``ensure_dirs()``
when a service starts.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

PACKAGE_DIR = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


@dataclass
class HoneypotConfig:
    """Core honeypot and environment configuration."""

    # Server Bind Settings
    host: str = "0.0.0.0"
    ssh_port: int = 2222
    tcp_port: int = 2323  # Telnet / raw TCP decoy
    http_port: int = 8080  # Web / Cloud API decoy
    dashboard_port: int = 8888  # Web UI Dashboard + internal JSON API

    # Where canary callbacks (GPS keys, beacons, AI-poison webhooks) point. Defaults to the HTTP decoy.
    callback_url: Optional[str] = None
    # Real GeoIP lookups (ip-api.com). Off by default: locations are synthetic and flagged as such.
    geoip_online: bool = False

    # Session retention (memory and on-disk JSONL) and OwnCloud session grouping
    max_sessions: int = 2000
    session_idle_seconds: int = 1800

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

    # Data & Log Directories (HONEYPOT_DATA_DIR; the package's data/ folder when unset)
    base_dir: Path = field(default_factory=lambda: PACKAGE_DIR)
    data_dir: Path = field(default_factory=lambda: PACKAGE_DIR / "data")
    logs_dir: Optional[Path] = None
    vault_dir: Optional[Path] = None
    rules_dir: Optional[Path] = None

    # Canary Tokens (Honey-Tokens for detecting cloud credential exfiltration)
    canary_aws_key_id: str = "HONEY_CANARY_AWS_KEY_DEMO_01"
    canary_aws_secret: str = "HONEY_CANARY_AWS_SECRET_PASS_TOKEN_DEMO_99"
    canary_db_connection: str = "postgresql://dbadmin:picoas_canary_pass@prod-db.internal:5432/customers"

    def __post_init__(self):
        """Derive data sub-directories (nothing is created here)."""
        self.data_dir = Path(self.data_dir)
        self.logs_dir = Path(self.logs_dir) if self.logs_dir else self.data_dir / "logs"
        self.vault_dir = Path(self.vault_dir) if self.vault_dir else self.data_dir / "vault"
        self.rules_dir = Path(self.rules_dir) if self.rules_dir else self.data_dir / "firewall_rules"
        if not self.callback_url:
            self.callback_url = f"http://127.0.0.1:{self.http_port}"
        self.callback_url = self.callback_url.rstrip("/")

    @property
    def sessions_file(self) -> Path:
        return self.logs_dir / "sessions.jsonl"

    @property
    def canary_registry_file(self) -> Path:
        return self.data_dir / "canaries" / "registry.json"

    @property
    def callback_host(self) -> str:
        return urlparse(self.callback_url).hostname or "127.0.0.1"

    @property
    def callback_port(self) -> int:
        parsed = urlparse(self.callback_url)
        return parsed.port or (443 if parsed.scheme == "https" else 80)

    def ensure_dirs(self) -> None:
        """Create the data directories (called when a service starts, never at import)."""
        for directory in (self.data_dir, self.logs_dir, self.vault_dir, self.rules_dir,
                          self.canary_registry_file.parent):
            directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.vault_dir, 0o700)
        except OSError:
            pass

    @classmethod
    def from_env(cls) -> "HoneypotConfig":
        """Build the configuration from HONEYPOT_* / GEOIP_ONLINE environment variables."""
        kwargs = {
            "host": os.environ.get("HONEYPOT_HOST", "").strip() or "0.0.0.0",
            "ssh_port": _env_int("HONEYPOT_SSH_PORT", 2222),
            "tcp_port": _env_int("HONEYPOT_TELNET_PORT", 2323),
            "http_port": _env_int("HONEYPOT_HTTP_PORT", 8080),
            "dashboard_port": _env_int("HONEYPOT_API_PORT", 8888),
            "callback_url": os.environ.get("HONEYPOT_CALLBACK_URL", "").strip() or None,
            "geoip_online": _env_bool("GEOIP_ONLINE", False),
            "max_sessions": max(_env_int("HONEYPOT_MAX_SESSIONS", 2000), 10),
        }
        hostname = os.environ.get("HONEYPOT_HOSTNAME", "").strip()
        if hostname:
            kwargs["hostname"] = hostname
        data_dir = os.environ.get("HONEYPOT_DATA_DIR", "").strip()
        if data_dir:
            kwargs["data_dir"] = Path(data_dir)
        return cls(**kwargs)


# Default shared singleton config (environment-driven, no filesystem side effects)
CONFIG = HoneypotConfig.from_env()
