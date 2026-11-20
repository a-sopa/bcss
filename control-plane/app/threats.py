"""Threat intelligence: the threat service (cloud_honeypot_ai) applied to every app's router.

Each router answers decoy paths (/.env, /.git/config, cloud credentials, wp-login…) with bait carrying the app's
canary credentials, catches any request that later uses a canary, and refuses blocked IPs. The control plane
forwards the routers' threat events to the service (sessions, MITRE ATT&CK mapping, bot classification, risk
score, sealing in the forensic vault) and blocks the attackers it recommends on every app. See docs/integration.md.
"""

import hashlib
import ipaddress
import json
import random
import threading
import time
from typing import Any

import httpx

from . import config

# This machine and its Docker networks (the console's own users arrive from the bridge gateway): never auto-blocked.
LOCAL_NETWORKS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
                                                     "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")]


class Unavailable(Exception):
    """The threat service could not be reached or answered with an error."""


def call(method: str, path: str, timeout: float = 5, **kwargs: Any) -> Any:
    try:
        response = httpx.request(method, f"{config.THREATS_URL}{path}", timeout=timeout, **kwargs)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise Unavailable(str(exc) or exc.__class__.__name__) from exc


def local_address(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(address in network for network in LOCAL_NETWORKS)


def valid_ip(ip: str) -> str | None:
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        return None


class Sentinel:
    """Per-app security configuration for the routers, and the flow of threat events to the service."""

    def __init__(self) -> None:
        self.cursors: dict[str, int] = {}  # app_id → last router event sequence forwarded
        self.canaries: dict[str, dict[str, str]] = {}
        self.dumps: dict[str, str] = {}
        self.written: dict[str, tuple[str, float]] = {}  # app_id → (digest, time) of the last security.json
        self.error: str | None = None
        self.lock = threading.Lock()

    def _bait(self, app_id: str) -> tuple[dict[str, str], str]:
        """The app's canary credentials and watermarked customer dump, created once by the threat service."""
        if app_id not in self.canaries:
            bundle = call("PUT", f"/api/canary/{app_id}") or {}
            bundle = bundle.get("bundle", bundle)
            self.canaries[app_id] = {key: str(bundle[key]) for key in
                                     ("api_key", "aws_access_key_id", "aws_secret_access_key", "jwt_secret") if bundle.get(key)}
        if app_id not in self.dumps:
            self.dumps[app_id] = (call("GET", f"/api/honeydump/{app_id}") or {}).get("sql", "")
        return self.canaries[app_id], self.dumps[app_id]

    def configure(self, runtime: Any, store: Any, record: dict[str, Any], force: bool = False) -> None:
        """Write the app's security.json: decoys on or off, canaries, honey dump and the global block list."""
        app_id = record["id"]
        try:
            canaries, dump = self._bait(app_id)
        except Unavailable:
            canaries, dump = {}, ""  # decoys and blocking still work without the service
        content = {"decoys": (record.get("security") or {}).get("decoys", True),
                   "blocked": [row["ip"] for row in store.blocked_ips()], "canaries": canaries, "honey_dump": dump}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        last = self.written.get(app_id)
        if force or last is None or last[0] != digest or time.time() - last[1] > 60:
            if runtime.write_router_file(app_id, "security.json", content):
                self.written[app_id] = (digest, time.time())

    def collect(self, runtime: Any, store: Any, record: dict[str, Any], metrics: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Forward the router's new threat events to the service; block what it recommends. Returns the verdicts."""
        app_id = record["id"]
        security = (metrics or {}).get("security") or {}
        events, seq = security.get("events") or [], security.get("seq", 0)
        with self.lock:
            cursor = self.cursors.get(app_id, 0)
            if seq < cursor:  # the router restarted
                cursor = 0
            fresh = [e for e in events if e.get("seq", 0) > cursor]
            if not fresh:
                self.cursors[app_id] = max(cursor, seq)
                return []
            try:
                result = call("POST", "/api/ingest", timeout=15, json={
                    "source": "owncloud", "app_id": app_id, "app_name": record["name"],
                    "events": [{k: e.get(k) for k in ("t", "ip", "method", "path", "user_agent", "kind", "status",
                                                      "username", "password", "canary")} for e in fresh],
                }) or {}
                self.error = None
            except Unavailable as exc:
                self.error = str(exc)
                return []  # retried on the next tick
            self.cursors[app_id] = seq
        verdicts = result.get("sessions") or []
        changed = False
        for verdict in verdicts:
            ip = verdict.get("ip") or ""
            if not verdict.get("recommend_block") or not config.AUTO_BLOCK or local_address(ip):
                continue
            techniques = ", ".join(m.get("id", "") for m in (verdict.get("mitre") or [])[:3])
            reason = (f"{verdict.get('threat_level', 'HIGH')} risk {verdict.get('risk_score', '?')}/100"
                      f"{' · canary used' if verdict.get('canary_triggered') else ''}{f' · {techniques}' if techniques else ''}")
            if store.block_ip(ip, reason, "auto", app_id, verdict.get("session_id")):
                changed = True
                store.add_event(app_id, "security", "warning", f"Blocked {ip} on every app",
                                f"{verdict.get('classification', 'Attacker')} on {record['name']}: {reason}.")
        if changed:
            self.push_blocklist(runtime, store)
        return verdicts

    def push_blocklist(self, runtime: Any, store: Any) -> None:
        for record in store.list_apps():
            if record["status"] in ("running", "canary"):
                try:
                    self.configure(runtime, store, record, force=True)
                except Exception:
                    continue

    def forget(self, app_id: str) -> None:
        with self.lock:
            for table in (self.cursors, self.canaries, self.dumps, self.written):
                table.pop(app_id, None)


# An attacker's typical run against a cloud app: reconnaissance of leaked secrets, credential stuffing, a data
# grab, then reuse of the stolen key. Executed inside the router so it reaches the app exactly like real traffic.
ATTACK_SCRIPT = r'''
import http.client, json, re, sys, time
ip, steps = sys.argv[1], []
def send(method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=10)
    h = {"X-OwnCloud-Simulated-Client": ip, "User-Agent": "python-requests/2.31.0 (scanner)", **(headers or {})}
    if body is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
    connection.request(method, path, body=body, headers=h)
    response = connection.getresponse()
    data = response.read().decode("utf-8", "replace")
    steps.append({"method": method, "path": path, "status": response.status})
    connection.close()
    time.sleep(0.15)
    return data
env = send("GET", "/.env")
send("GET", "/.git/config")
send("GET", "/latest/meta-data/iam/security-credentials/")
send("GET", "/latest/meta-data/iam/security-credentials/app-instance-role")
for password in ("admin", "123456", "Password1!"):
    send("POST", "/wp-login.php", body=f"log=admin&pwd={password}")
send("GET", "/backup.sql")
stolen = re.search(r"STRIPE_SECRET_KEY=(\S+)", env)
if stolen:
    send("GET", "/api/orders?limit=100", headers={"Authorization": f"Bearer {stolen.group(1)}"})
send("GET", "/")
print(json.dumps({"ip": ip, "steps": steps, "stolen_key_reused": bool(stolen)}))
'''


def simulated_attacker() -> str:
    """An address from TEST-NET-3 (RFC 5737, documentation only): never a real host."""
    return f"203.0.113.{random.randint(2, 254)}"
