"""SSH Honeypot Server supporting banner negotiation, credential capture, and fake shell."""

import logging
import socket
import threading
import time
from typing import Optional

from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.fake_shell import FakeShell
from cloud_honeypot_ai.core.session import GLOBAL_SESSION_MANAGER, SessionManager

logger = logging.getLogger("honeypot.ssh")


class SSHHoneypotServer:
    """Socket-level SSH honeypot server.

    Captures automated bot scans, SSH banner probes, credential brute-forcing,
    and drops accepted sessions into an interactive simulated shell.
    """

    SSH_BANNER = b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.1\r\n"

    def __init__(
        self,
        host: str = CONFIG.host,
        port: int = CONFIG.ssh_port,
        session_mgr: Optional[SessionManager] = None,
    ):
        self.host = host
        self.port = port
        self.session_mgr = session_mgr or GLOBAL_SESSION_MANAGER
        self.running = False
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start listening for incoming SSH connections."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(50)
        self.running = True

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info("SSH Honeypot listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Stop SSH server gracefully."""
        self.running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("SSH Honeypot stopped.")

    def _accept_loop(self) -> None:
        while self.running:
            try:
                client_sock, (client_ip, client_port) = self._sock.accept()
                client_thread = threading.Thread(
                    target=self._handle_ssh_client,
                    args=(client_sock, client_ip, client_port),
                    daemon=True,
                )
                client_thread.start()
            except Exception:
                if not self.running:
                    break

    def _handle_ssh_client(self, sock: socket.socket, client_ip: str, client_port: int) -> None:
        """Handle incoming SSH probe, banner exchange, and command emulation."""
        session = self.session_mgr.create_session(
            remote_ip=client_ip,
            remote_port=client_port,
            protocol="SSH",
        )
        sock.settimeout(30.0)

        def send_raw(data: bytes) -> None:
            sock.sendall(data)

        try:
            # 1. Send OpenSSH protocol identification banner
            send_raw(self.SSH_BANNER)

            # 2. Read client identification banner or initial payload
            client_banner = sock.recv(1024)
            if not client_banner:
                return

            client_banner_str = client_banner.decode("utf-8", errors="replace").strip()
            session.record_command(f"BANNER_EXCHANGE: {client_banner_str}", "Sent SSH-2.0-OpenSSH_8.9p1")

            # Check if this is an automated bot or terminal interactive
            # If the client sent a plaintext password attempt or raw input:
            time.sleep(0.2)
            sock.settimeout(4.0)

            authenticated = False
            username = "root"

            # Allow capturing passwords sent directly or via login prompts
            try:
                probe_data = sock.recv(2048)
                if probe_data:
                    raw_str = probe_data.decode("utf-8", errors="replace").strip()
                    # Check if username/password appears in payload
                    extracted_creds = self._extract_credentials(raw_str)
                    for user, pwd in extracted_creds:
                        success = pwd.lower() in CONFIG.weak_passwords or pwd == "admin123"
                        session.record_auth_attempt(user, pwd, success=success, protocol="SSH")
                        if success:
                            authenticated = True
                            username = user
            except socket.timeout:
                pass

            # If not yet authenticated, simulate fallback password prompt for terminal clients
            if not authenticated:
                try:
                    send_raw(b"login as: ")
                    sock.settimeout(30.0)
                    user_bytes = sock.recv(512)
                    if user_bytes:
                        username = user_bytes.decode("utf-8", errors="replace").strip()
                        send_raw(f"{username}@{CONFIG.hostname}'s password: ".encode("utf-8"))
                        pass_bytes = sock.recv(512)
                        if pass_bytes:
                            password = pass_bytes.decode("utf-8", errors="replace").strip()
                            success = password.lower() in CONFIG.weak_passwords or password == "admin123"
                            session.record_auth_attempt(username, password, success=success, protocol="SSH")
                            if success:
                                authenticated = True
                except Exception:
                    pass

            # If authenticated, grant fake shell access
            if authenticated:
                send_raw(
                    f"\r\nWelcome to Ubuntu 22.04.4 LTS (GNU/Linux {CONFIG.kernel_release} {CONFIG.architecture})\r\n"
                    f"Last login: Fri Nov 20 09:14:22 2026 from {client_ip}\r\n\r\n".encode("utf-8")
                )
                shell = FakeShell(username=username)

                while self.running:
                    prompt = shell.get_prompt().replace("\n", "\r\n")
                    send_raw(prompt.encode("utf-8"))
                    sock.settimeout(60.0)
                    line_data = b""
                    while not line_data.endswith(b"\n"):
                        ch = sock.recv(1)
                        if not ch:
                            return
                        line_data += ch
                    cmd_line = line_data.decode("utf-8", errors="replace").strip()
                    if not cmd_line:
                        continue

                    res = shell.execute(cmd_line)
                    session.record_command(cmd_line, res.stdout, res.canary_triggered)

                    if res.stdout:
                        send_raw(res.stdout.replace("\n", "\r\n").encode("utf-8"))

                    if res.should_exit:
                        break

        except socket.timeout:
            pass
        except Exception as e:
            logger.debug("SSH handler error: %s", e)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self.session_mgr.close_session(session.session_id)

    def _extract_credentials(self, text: str) -> list[tuple[str, str]]:
        """Extract potential username/password pairs from raw payload."""
        results = []
        for line in text.splitlines():
            if ":" in line:
                parts = line.split(":", 1)
                results.append((parts[0].strip(), parts[1].strip()))
            elif " " in line:
                parts = line.split(" ", 1)
                results.append((parts[0].strip(), parts[1].strip()))
        if not results and text:
            # Assume it's a password probe
            results.append(("root", text))
        return results
