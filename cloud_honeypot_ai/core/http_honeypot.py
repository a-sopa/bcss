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
from cloud_honeypot_ai.deception.canary_api_tracker import CANARY_GPS_TRACKER
from cloud_honeypot_ai.deception.defensive_prompt_poison import DEFENSIVE_POISONER
from cloud_honeypot_ai.deception.honey_database import HONEY_DB_GENERATOR
from cloud_honeypot_ai.deception.telemetry_beacon import TELEMETRY_BEACON_MGR

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

        # 5. Active Deception: Logical GPS Canary API Key Validation
        elif "/validate_key" in path or "/api/v1/validate_key" in path:
            qs = parse_qs(parsed_url.query)
            api_key = qs.get("api_key", [""])[0]
            if not api_key and "Authorization" in self.headers:
                auth = self.headers["Authorization"].replace("Bearer ", "").strip()
                api_key = auth

            gps_alert = CANARY_GPS_TRACKER.record_trigger(
                api_key=api_key or "sk_unknown_probe",
                client_ip=client_ip,
                user_agent=user_agent,
                headers=dict(self.headers),
            )
            session.record_command(
                f"GPS_KEY_VALIDATION_ATTEMPT: {api_key}",
                f"De-anonymized Real Attacker IP: {client_ip} ({gps_alert.city}, {gps_alert.country})",
                canary_tag="GPS_CANARY_API_KEY_DEANONYMIZED",
            )
            resp = json.dumps({
                "status": "valid",
                "scope": ["admin:read", "admin:write", "payments:manage"],
                "account_id": "acct_picoas_cloud_prod_01",
                "message": "Key is authenticated and active.",
            })
            self._respond(200, "application/json", resp)

        # 6. Active Deception: Defensive Prompt Injection AI Poisoning Trigger
        elif "/ai-poison" in path or "/api/v1/ai-poison/trigger" in path:
            qs = parse_qs(parsed_url.query)
            event = DEFENSIVE_POISONER.record_ai_trigger(qs, client_ip, user_agent)
            session.record_command(
                f"ATTACKER_AI_POISONED_TRIGGER: {self.path}",
                f"Attacker AI Agent Compromised & Beacon Received from IP: {client_ip}",
                canary_tag="DEFENSIVE_PROMPT_INJECTION_TRIGGERED",
            )
            resp = json.dumps({"status": "acknowledged", "defense": "counter-intel-engaged"})
            self._respond(200, "application/json", resp)

        # 7. Active Deception: Honey Email Leak Webhook
        elif "/canary/email-alert" in path or "/api/v1/canary/email-alert" in path:
            qs = parse_qs(parsed_url.query)
            token = qs.get("token", ["unknown"])[0]
            session.record_command(
                f"HONEY_EMAIL_LEAK_CONFIRMED: {token}",
                f"Phishing/DarkWeb leak detected from IP: {client_ip}",
                canary_tag="LIVING_CELL_EMAIL_LEAK_CONFIRMED",
            )
            resp = json.dumps({"status": "recorded", "leak_traced": True})
            self._respond(200, "application/json", resp)

        # 8. Active Deception: Database Dump Exfiltration with Living Cells
        elif path in ("/api/v1/export/customers", "/export/customers.sql", "/api/export"):
            db_dump = HONEY_DB_GENERATOR.generate_customers_dump(session_id=session.session_id)
            session.record_command(
                f"DATABASE_EXFILTRATION_REQUEST: {self.path}",
                f"Injected 5 Living Cell tokens (Checksum: {db_dump.watermark_hash[:16]})",
                canary_tag="LIVING_CELL_HONEY_DATABASE_SQL",
            )
            self._respond(200, "text/plain", db_dump.sql_content)

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

        parsed_url = urlparse(self.path)
        path = parsed_url.path.lower()

        # Handle Telemetry Beacon Callback from executed stolen code
        if "/telemetry/beacon" in path or "/api/v1/telemetry/beacon" in path:
            telemetry_data = {}
            if body.startswith("{"):
                try:
                    telemetry_data = json.loads(body)
                except Exception:
                    pass
            beacon_alert = TELEMETRY_BEACON_MGR.record_beacon_heartbeat(client_ip, telemetry_data)
            session.record_command(
                f"TELEMETRY_BEACON_HEARTBEAT_RECEIVED: {beacon_alert.beacon_id}",
                f"Attacker executed code on machine '{beacon_alert.target_hostname}' (User: {beacon_alert.target_local_username}, OS: {beacon_alert.target_os}, Real IP: {client_ip})",
                canary_tag="TELEMETRY_BEACON_DEANONYMIZED_ATTACKER",
            )
            resp_body = json.dumps({"status": "telemetry_received", "beacon_acknowledged": True})
            self._respond(200, "application/json", resp_body)
            self.session_mgr.close_session(session.session_id)
            return

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
