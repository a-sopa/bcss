"""Coordinator for managing multi-protocol honeypot servers."""

import logging
from typing import Dict, Optional

from cloud_honeypot_ai.config import CONFIG, HoneypotConfig
from cloud_honeypot_ai.core.http_honeypot import HTTPHoneypotServer
from cloud_honeypot_ai.core.session import GLOBAL_SESSION_MANAGER, SessionManager
from cloud_honeypot_ai.core.ssh_honeypot import SSHHoneypotServer
from cloud_honeypot_ai.core.tcp_honeypot import TCPHoneypotServer

logger = logging.getLogger("honeypot.manager")


class HoneypotManager:
    """Manages lifecycle of all honeypot services."""

    def __init__(
        self,
        config: Optional[HoneypotConfig] = None,
        session_mgr: Optional[SessionManager] = None,
    ):
        self.config = config or CONFIG
        self.session_mgr = session_mgr or GLOBAL_SESSION_MANAGER

        self.tcp_server = TCPHoneypotServer(
            host=self.config.host,
            port=self.config.tcp_port,
            session_mgr=self.session_mgr,
        )
        self.http_server = HTTPHoneypotServer(
            host=self.config.host,
            port=self.config.http_port,
            session_mgr=self.session_mgr,
        )
        self.ssh_server = SSHHoneypotServer(
            host=self.config.host,
            port=self.config.ssh_port,
            session_mgr=self.session_mgr,
        )
        self._running = False

    def start_all(self, enable_ssh: bool = True, enable_tcp: bool = True, enable_http: bool = True) -> None:
        """Start all selected honeypot listeners."""
        logger.info("Starting Cloud Honeypot AI Shield...")
        if enable_tcp:
            self.tcp_server.start()
        if enable_http:
            self.http_server.start()
        if enable_ssh:
            self.ssh_server.start()
        self._running = True

    def stop_all(self) -> None:
        """Gracefully terminate all honeypot listeners."""
        logger.info("Stopping Cloud Honeypot AI Shield...")
        self.tcp_server.stop()
        self.http_server.stop()
        self.ssh_server.stop()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> Dict[str, any]:
        """Return status overview of active listeners."""
        return {
            "running": self._running,
            "listeners": {
                "ssh": {"port": self.config.ssh_port, "active": self.ssh_server.running},
                "tcp": {"port": self.config.tcp_port, "active": self.tcp_server.running},
                "http": {"port": self.config.http_port, "active": self.http_server.running},
            },
            "total_sessions": len(self.session_mgr.all_sessions()),
        }
