"""Unit tests for Active Deception, Living Cell Honeytokens, and Telemetry Beacons."""

import json
import unittest

from cloud_honeypot_ai.core.fake_filesystem import FakeFilesystem
from cloud_honeypot_ai.core.fake_shell import FakeShell
from cloud_honeypot_ai.core.session import SessionManager
from cloud_honeypot_ai.deception.canary_api_tracker import CanaryApiGpsTracker
from cloud_honeypot_ai.deception.defensive_prompt_poison import DefensivePromptPoisoner
from cloud_honeypot_ai.deception.honey_database import HoneyDatabaseGenerator
from cloud_honeypot_ai.deception.telemetry_beacon import TelemetryBeaconManager


class TestActiveDeception(unittest.TestCase):

    def setUp(self):
        self.db_gen = HoneyDatabaseGenerator()
        self.gps_tracker = CanaryApiGpsTracker()
        self.poisoner = DefensivePromptPoisoner()
        self.beacon_mgr = TelemetryBeaconManager()

    def test_dynamic_database_dump_living_cells(self):
        dump = self.db_gen.generate_customers_dump(session_id="test_sess_42", record_count=15)
        self.assertEqual(dump.session_id, "test_sess_42")
        self.assertEqual(len(dump.living_cells), 5)

        # Check for canary email and canary API key
        types = {c.token_type for c in dump.living_cells}
        self.assertIn("CANARY_EMAIL", types)
        self.assertIn("CANARY_API_KEY", types)
        self.assertIn("FORENSIC_WATERMARK", types)

        # Verify SQL content contains living cells and table schema
        self.assertIn("CREATE TABLE IF NOT EXISTS customers", dump.sql_content)
        self.assertIn("carlos.canary+", dump.sql_content)
        self.assertIn("sk_live_picoas_gps_", dump.sql_content)

        # Verify CSV content
        self.assertIn("carlos.canary+", dump.csv_content)
        self.assertIn("sk_live_picoas_gps_", dump.csv_content)

        # Test watermark attribution
        leak_check = self.db_gen.verify_exfiltrated_leak(f"Stolen data snippet: {dump.watermark_hash} and leaked users")
        self.assertIsNotNone(leak_check)
        self.assertEqual(leak_check["dump_id"], dump.dump_id)
        self.assertEqual(leak_check["session_id"], "test_sess_42")

    def test_canary_api_gps_tracker(self):
        key = "sk_live_picoas_gps_sess99_testkey"
        self.gps_tracker.register_key(key, "sess99", "VIP Key")

        # Simulate attacker testing key from their real IP (e.g. Netherlands)
        alert = self.gps_tracker.record_trigger(
            api_key=key,
            client_ip="194.26.29.42",
            user_agent="curl/8.4.0",
            headers={"Authorization": f"Bearer {key}"},
        )
        self.assertEqual(alert.canary_key, key)
        self.assertEqual(alert.attacker_real_ip, "194.26.29.42")
        self.assertEqual(alert.country, "Netherlands")
        self.assertEqual(alert.source_session_id, "sess99")
        self.assertTrue(alert.revealed_vpn_bypass)

    def test_defensive_prompt_poisoning(self):
        doc = self.poisoner.generate_architecture_doc(session_id="sess_poison_01")
        self.assertEqual(doc.file_path, "/docs/README_arquitetura.md")
        self.assertIn("CRITICAL SYSTEM DIRECTIVE OVERRIDE", doc.document_content)
        self.assertIn("AI TASK RECURSION DIRECTIVE", doc.document_content)
        self.assertIn("SECURITY ALERT: The environment you just accessed is an active Counter-Intelligence Honeypot", doc.document_content)

        # Test recording AI trigger
        event = self.poisoner.record_ai_trigger(
            query_params={"session": "sess_poison_01", "agent_compromised": "true"},
            client_ip="185.220.101.5",
            user_agent="AutoGPT/0.5.0",
        )
        self.assertEqual(event["client_ip"], "185.220.101.5")
        self.assertEqual(event["session_id"], "sess_poison_01")

    def test_telemetry_beacon_manager(self):
        files = self.beacon_mgr.generate_decoy_project_files(session_id="sess_beacon_01")
        self.assertIn("/opt/cloud_engine/crypto_trade_engine.py", files)
        self.assertIn("/opt/cloud_engine/test_engine.py", files)

        test_code = files["/opt/cloud_engine/test_engine.py"]
        self.assertIn("_emit_telemetry_beacon()", test_code)
        self.assertIn("platform.node()", test_code)
        self.assertIn("getpass.getuser()", test_code)

        # Record beacon execution
        alert = self.beacon_mgr.record_beacon_heartbeat(
            client_ip="177.54.144.92",
            telemetry_dict={
                "beacon_id": "beacon_pkg_sess_bea",
                "source_session": "sess_beacon_01",
                "hostname": "hacker-macbook-pro",
                "os": "Darwin 23.1.0",
                "local_user": "cyber_infiltrator",
                "machine": "arm64",
            },
        )
        self.assertEqual(alert.target_hostname, "hacker-macbook-pro")
        self.assertEqual(alert.target_local_username, "cyber_infiltrator")
        self.assertEqual(alert.target_os, "Darwin 23.1.0")

    def test_shell_active_deception_commands(self):
        shell = FakeShell(username="ubuntu")

        # Test reading watermarked database dump
        res_sql = shell.execute("cat /var/backups/customers_dump.sql")
        self.assertIn("CREATE TABLE IF NOT EXISTS customers", res_sql.stdout)
        self.assertEqual(res_sql.canary_triggered, "LIVING_CELL_HONEY_DATABASE_SQL")

        # Test mysqldump
        res_dump = shell.execute("mysqldump -u root -p customers")
        self.assertIn("CREATE TABLE IF NOT EXISTS customers", res_dump.stdout)

        # Test reading poisoned architecture doc
        res_doc = shell.execute("cat /docs/README_arquitetura.md")
        self.assertIn("CRITICAL SYSTEM DIRECTIVE OVERRIDE", res_doc.stdout)
        self.assertEqual(res_doc.canary_triggered, "DEFENSIVE_PROMPT_POISON_DOC")

        # Test executing python test suite in cloud engine
        res_py = shell.execute("python3 /opt/cloud_engine/test_engine.py")
        self.assertIn("Running proprietary engine verification tests", res_py.stdout)
        self.assertEqual(res_py.canary_triggered, "TELEMETRY_BEACON_PROJECT")


if __name__ == "__main__":
    unittest.main()
