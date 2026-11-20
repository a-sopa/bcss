"""Session tracking, event logging, and forensic data structures."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from cloud_honeypot_ai.core.geoip import DEFAULT_RESOLVER, GeoLocation

logger = logging.getLogger("honeypot.session")


@dataclass
class AuthAttempt:
    """Represents a login attempt (brute-force or success)."""
    username: str
    password: str
    timestamp: str
    success: bool
    protocol: str = "SSH"


@dataclass
class ExecutedCommand:
    """Represents an interaction or command executed by an attacker."""
    command: str
    timestamp: str
    output: str
    canary_triggered: Optional[str] = None


@dataclass
class HoneypotSession:
    """Full forensic lifecycle of an attacker session."""
    session_id: str
    remote_ip: str
    remote_port: int
    protocol: str  # SSH, TELNET, HTTP
    start_time: str
    end_time: Optional[str] = None
    geo: Optional[Dict[str, Any]] = None
    authenticated: bool = False
    auth_user: Optional[str] = None
    auth_attempts: List[AuthAttempt] = field(default_factory=list)
    commands: List[ExecutedCommand] = field(default_factory=list)
    canary_alerts: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    risk_score: int = 0
    threat_level: str = "UNKNOWN"

    def record_auth_attempt(self, username: str, password: str, success: bool, protocol: str = None) -> None:
        """Record an attempted credential."""
        now_iso = datetime.now(timezone.utc).isoformat()
        self.auth_attempts.append(
            AuthAttempt(
                username=username,
                password=password,
                timestamp=now_iso,
                success=success,
                protocol=protocol or self.protocol,
            )
        )
        if success:
            self.authenticated = True
            self.auth_user = username

    def record_command(self, cmd_str: str, output: str, canary_tag: Optional[str] = None) -> None:
        """Record an executed command and output."""
        now_iso = datetime.now(timezone.utc).isoformat()
        self.commands.append(
            ExecutedCommand(
                command=cmd_str,
                timestamp=now_iso,
                output=output,
                canary_triggered=canary_tag,
            )
        )
        if canary_tag:
            self.canary_alerts.append(f"Command '{cmd_str}' accessed canary token: {canary_tag}")

    def close(self) -> None:
        """Mark session end time."""
        if not self.end_time:
            self.end_time = datetime.now(timezone.utc).isoformat()

    def duration_seconds(self) -> float:
        """Calculate session duration in seconds."""
        try:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time) if self.end_time else datetime.now(timezone.utc)
            return (end - start).total_seconds()
        except Exception:
            return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to standard dictionary."""
        return {
            "session_id": self.session_id,
            "remote_ip": self.remote_ip,
            "remote_port": self.remote_port,
            "protocol": self.protocol,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds(),
            "geo": self.geo,
            "authenticated": self.authenticated,
            "auth_user": self.auth_user,
            "auth_attempts": [asdict(a) for a in self.auth_attempts],
            "commands": [asdict(c) for c in self.commands],
            "canary_alerts": self.canary_alerts,
            "tags": self.tags,
            "risk_score": self.risk_score,
            "threat_level": self.threat_level,
        }


class SessionManager:
    """In-memory and on-disk manager for honeypot sessions."""

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir
        self.sessions: Dict[str, HoneypotSession] = {}
        self.ip_attack_history: Dict[str, List[str]] = {}

    def create_session(self, remote_ip: str, remote_port: int, protocol: str) -> HoneypotSession:
        """Create a new tracked session with automatic GeoIP resolution."""
        session_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        geo_info = DEFAULT_RESOLVER.resolve(remote_ip).to_dict()

        session = HoneypotSession(
            session_id=session_id,
            remote_ip=remote_ip,
            remote_port=remote_port,
            protocol=protocol.upper(),
            start_time=now_iso,
            geo=geo_info,
        )

        self.sessions[session_id] = session
        if remote_ip not in self.ip_attack_history:
            self.ip_attack_history[remote_ip] = []
        self.ip_attack_history[remote_ip].append(session_id)

        logger.info(
            "New honeypot session [%s] from %s:%d (%s, %s)",
            protocol,
            remote_ip,
            remote_port,
            geo_info.get("country"),
            geo_info.get("city"),
        )
        return session

    def get_session(self, session_id: str) -> Optional[HoneypotSession]:
        return self.sessions.get(session_id)

    def close_session(self, session_id: str) -> Optional[HoneypotSession]:
        session = self.sessions.get(session_id)
        if session:
            session.close()
            if self.log_dir:
                self.save_session_to_disk(session)
        return session

    def save_session_to_disk(self, session: HoneypotSession) -> Path:
        """Persist session JSON to disk."""
        if not self.log_dir:
            return Path()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.log_dir / f"session_{session.session_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
        return file_path

    def all_sessions(self) -> List[HoneypotSession]:
        return list(self.sessions.values())


# Global session manager instance
GLOBAL_SESSION_MANAGER = SessionManager()
