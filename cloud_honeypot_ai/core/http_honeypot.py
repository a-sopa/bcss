"""Web and Cloud API Decoy Honeypot Server."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import socketserver
import threading
from typing import Optional
from urllib.parse import parse_qs, urlparse

from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.session import GLOBAL_SESSION_MANAGER, SessionManager

logger = logging.getLogger("honeypot.http")


class HoneypotHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler designed to trap automated cloud scanners and bots."""

    def log_message(self, format: str, *args) -> None:
        # Suppress standard noisy console logs; events are recorded in SessionManager
        logger.debug(format % args)

    @property
    def session_mgr(self) -> SessionManager:
        return getattr(self.server, "session_mgr", GLOBAL_SESSION_MANAGER)

    def do_GET(self) -> None:
        """Handle incoming GET requests looking for exposed cloud credentials."""
        client_ip = self.client_address[0]
        client_port = self.client_address[1]
        session = self.session_mgr.create_session(
            remote_ip=client_ip,
            remote_port=client_port,
            protocol="HTTP",
        )

        parsed_url = urlparse(self.path)
        path = parsed_url.path.lower()
        user_agent = self.headers.get("User-Agent", "Unknown")

        # 1. Target: .env file exposure
        if path in ("/.env", "/env", "/app/.env", "/.git/config"):
            payload = (
                "NODE_ENV=production\n"
                f"AWS_ACCESS_KEY_ID={CONFIG.canary_aws_key_id}\n"
                f"AWS_SECRET_ACCESS_KEY={CONFIG.canary_aws_secret}\n"
                f"DATABASE_URL={CONFIG.canary_db_connection}\n"
                "JWT_SECRET=super_secret_picoas_cloud_jwt_key_2026\n"
            )
            session.record_command(f"GET {self.path} (UA: {user_agent})", payload, "CANARY_ENV_FILE_LEAK")
            self._respond(200, "text/plain", payload)

        # 2. Target: Cloud IMDS / AWS Metadata SSRF attack
        elif "meta-data" in path or "security-credentials" in path or "aws" in path:
            payload = json.dumps(
                {
                    "Code": "Success",
                    "LastUpdated": "2026-11-20T09:12:00Z",
                    "Type": "AWS-HMAC",
                    "AccessKeyId": CONFIG.canary_aws_key_id,
                    "SecretAccessKey": CONFIG.canary_aws_secret,
                    "Token": "CANARY_SESSION_TOKEN_PICOAS_2026",
                    "Expiration": "2026-11-20T18:00:00Z",
                },
                indent=2,
            )
            session.record_command(f"GET {self.path} (SSRF scan)", payload, "CANARY_AWS_CREDENTIAL_STOLEN")
            self._respond(200, "application/json", payload)

        # 3. Target: Spring Boot actuator exposure
        elif "/actuator" in path:
            payload = json.dumps({"status": "UP", "cloudProvider": "AWS", "env": "prod"}, indent=2)
            session.record_command(f"GET {self.path}", payload, "ACTUATOR_SCAN")
            self._respond(200, "application/json", payload)

        # 4. Target: Admin login portals (phpmyadmin, wp-login, admin)
        elif path in ("/admin", "/login", "/phpmyadmin", "/wp-login.php", "/dashboard"):
            html = (
                "<!DOCTYPE html><html><head><title>Cloud Management Login</title></head>"
                "<body style='font-family:sans-serif;background:#0f172a;color:#f8fafc;padding:50px;text-align:center;'>"
                "<h2>Cloud Admin Portal</h2>"
                "<form method='POST' action='/login'>"
                "<input name='username' placeholder='Username' style='padding:8px;margin:5px;'><br>"
                "<input name='password' type='password' placeholder='Password' style='padding:8px;margin:5px;'><br>"
                "<button type='submit' style='padding:8px 20px;background:#38bdf8;border:none;cursor:pointer;'>Sign In</button>"
                "</form></body></html>"
            )
            session.record_command(f"GET {self.path}", "Rendered Fake Admin Login Page")
            self._respond(200, "text/html", html)

        # Default root
        else:
            payload = json.dumps(
                {
                    "system": "Cloud Gateway",
                    "status": "online",
                    "version": "1.0.4",
                    "node": CONFIG.hostname,
                }
            )
            session.record_command(f"GET {self.path}", payload)
            self._respond(200, "application/json", payload)

        self.session_mgr.close_session(session.session_id)

    def do_POST(self) -> None:
        """Handle incoming POST credential stuffing and login attempts."""
        client_ip = self.client_address[0]
        client_port = self.client_address[1]
        session = self.session_mgr.create_session(
            remote_ip=client_ip,
            remote_port=client_port,
            protocol="HTTP",
        )

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8", errors="replace") if content_length > 0 else ""

        username = "unknown"
        password = "unknown"

        # Try to parse form-encoded or JSON body
        if body.startswith("{"):
            try:
                data = json.loads(body)
                username = data.get("username") or data.get("user") or data.get("email") or "unknown"
                password = data.get("password") or data.get("pass") or "unknown"
            except Exception:
                pass
        else:
            try:
                data = parse_qs(body)
                username = data.get("username", ["unknown"])[0]
                password = data.get("password", ["unknown"])[0]
            except Exception:
                pass

        # Evaluate if password is in weak credentials
        success = password.lower() in CONFIG.weak_passwords or password == "admin123"
        session.record_auth_attempt(username, password, success=success, protocol="HTTP")
        session.record_command(f"POST {self.path} (Body: {body[:100]})", "Captured Web Credential Attack")

        if success:
            resp_body = json.dumps({"status": "authenticated", "token": "cloud_token_admin_ok", "user": username})
            self._respond(200, "application/json", resp_body)
        else:
            resp_body = json.dumps({"status": "error", "message": "Invalid credentials"})
            self._respond(401, "application/json", resp_body)

        self.session_mgr.close_session(session.session_id)

    def _respond(self, status: int, content_type: str, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Server", "nginx/1.18.0 (Ubuntu)")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


class HTTPHoneypotServer:
    """HTTP honeypot server manager."""

    def __init__(
        self,
        host: str = CONFIG.host,
        port: int = CONFIG.http_port,
        session_mgr: Optional[SessionManager] = None,
    ):
        self.host = host
        self.port = port
        self.session_mgr = session_mgr or GLOBAL_SESSION_MANAGER
        self.running = False
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start HTTP server in background thread."""
        server_address = (self.host, self.port)

        class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
            daemon_threads = True

        self._httpd = ThreadingHTTPServer(server_address, HoneypotHTTPHandler)
        self._httpd.session_mgr = self.session_mgr
        self.running = True

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("HTTP Honeypot listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Stop HTTP server."""
        self.running = False
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("HTTP Honeypot stopped.")
