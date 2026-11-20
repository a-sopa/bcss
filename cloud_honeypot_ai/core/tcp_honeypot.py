"""Interactive TCP / Telnet honeypot server simulating cloud terminal access."""

import logging
import socket
import threading
import time
from typing import Optional

from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.fake_shell import FakeShell
from cloud_honeypot_ai.core.session import GLOBAL_SESSION_MANAGER, SessionManager

logger = logging.getLogger("honeypot.tcp")


class TCPHoneypotServer:
    """Multi-threaded TCP honeypot simulating interactive cloud terminal."""

    def __init__(
        self,
        host: str = CONFIG.host,
        port: int = CONFIG.tcp_port,
        session_mgr: Optional[SessionManager] = None,
        max_auth_attempts: int = 5,
    ):
        self.host = host
        self.port = port
        self.session_mgr = session_mgr or GLOBAL_SESSION_MANAGER
        self.max_auth_attempts = max_auth_attempts
        self.running = False
        self._server_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start listening for incoming connections in a background thread."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(50)
        self.running = True

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info("TCP Honeypot listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Stop server gracefully."""
        self.running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("TCP Honeypot stopped.")

    def _accept_loop(self) -> None:
        """Accept incoming attacker connections."""
        while self.running:
            try:
                client_sock, (client_ip, client_port) = self._server_socket.accept()
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_ip, client_port),
                    daemon=True,
                )
                client_thread.start()
            except Exception:
                if not self.running:
                    break

    def _handle_client(self, sock: socket.socket, client_ip: str, client_port: int) -> None:
        """Handle individual attacker connection."""
        session = self.session_mgr.create_session(
            remote_ip=client_ip,
            remote_port=client_port,
            protocol="TELNET",
        )
        sock.settimeout(60.0)

        def send_line(text: str) -> None:
            sock.sendall((text.replace("\n", "\r\n")).encode("utf-8", errors="replace"))

        def read_line() -> Optional[str]:
            buf = []
            while True:
                ch = sock.recv(1)
                if not ch:
                    return None
                if ch == b"\n":
                    break
                if ch == b"\r":
                    continue
                buf.append(ch)
            return b"".join(buf).decode("utf-8", errors="replace").strip()

        try:
            # Banner
            send_line(f"Ubuntu 22.04.4 LTS ({CONFIG.hostname})\n")

            authenticated = False
            username = ""
            attempts = 0

            # Authentication loop: bait the attacker with weak password acceptance
            while attempts < self.max_auth_attempts and not authenticated:
                attempts += 1
                send_line(f"{CONFIG.hostname} login: ")
                user_input = read_line()
                if user_input is None:
                    break
                username = user_input.strip()

                send_line("Password: ")
                pass_input = read_line()
                if pass_input is None:
                    break
                password = pass_input.strip()

                # Check if password is in honey weak password set
                if password.lower() in CONFIG.weak_passwords or password == "admin123":
                    authenticated = True
                    session.record_auth_attempt(username, password, success=True, protocol="TELNET")
                    send_line("\nLogin successful.\n")
                    break
                else:
                    session.record_auth_attempt(username, password, success=False, protocol="TELNET")
                    time.sleep(0.5)  # Realistic authentication delay
                    send_line("\nLogin incorrect\n\n")

            if not authenticated:
                send_line("Too many authentication failures\n")
                return

            # Interactive Shell session
            shell = FakeShell(username=username)
            send_line(
                f"\nWelcome to Ubuntu 22.04.4 LTS (GNU/Linux {CONFIG.kernel_release} {CONFIG.architecture})\n"
                " * Documentation:  https://help.ubuntu.com\n"
                " * Management:     https://landscape.canonical.com\n"
                f" * Cloud Instance: {CONFIG.cloud_provider}\n\n"
            )

            while self.running:
                prompt = shell.get_prompt()
                sock.sendall(prompt.encode("utf-8"))
                cmd_line = read_line()
                if cmd_line is None:
                    break
                if not cmd_line.strip():
                    continue

                # Execute in simulated shell
                res = shell.execute(cmd_line)
                session.record_command(cmd_line, res.stdout, res.canary_triggered)

                if res.stdout:
                    send_line(res.stdout)

                if res.should_exit:
                    break

        except socket.timeout:
            send_line("\nConnection timed out.\n")
        except Exception as e:
            logger.debug("Client handler error: %s", e)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self.session_mgr.close_session(session.session_id)
