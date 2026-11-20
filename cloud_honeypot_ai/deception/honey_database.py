"""Dynamic Honey Database Generator with 'Living Cells' (Watermarked Honeytokens)."""

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LivingCellToken:
    """An individual active honeytoken injected into a dynamic database dump."""
    cell_id: str
    token_type: str  # CANARY_EMAIL, CANARY_API_KEY, CANARY_IBAN, FORENSIC_WATERMARK
    label: str
    token_value: str
    tracking_payload: str
    description: str


@dataclass
class HoneyDatabaseDump:
    """Generated synthetic database dump containing living cell tokens."""
    dump_id: str
    generated_at: str
    session_id: str
    table_name: str
    total_records: int
    living_cells: List[LivingCellToken]
    watermark_hash: str
    sql_content: str
    csv_content: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dump_id": self.dump_id,
            "generated_at": self.generated_at,
            "session_id": self.session_id,
            "table_name": self.table_name,
            "total_records": self.total_records,
            "living_cells": [asdict(c) for c in self.living_cells],
            "watermark_hash": self.watermark_hash,
            "sql_preview": self.sql_content[:400] + "...",
            "csv_preview": self.csv_content[:400] + "...",
        }


# Base pool of realistic names and domains for synthetic customer data
NAMES_POOL = [
    ("Sofia Martins", "TechVentures Lisboa", "912345678", "Lisboa"),
    ("João Silva", "Banco Atlântico", "934567890", "Porto"),
    ("Mariana Costa", "Inovação Cloud SA", "967890123", "Coimbra"),
    ("Tiago Ferreira", "FinTech Iberia", "923456781", "Braga"),
    ("Beatriz Santos", "Retail Solutions PT", "914567892", "Faro"),
    ("Pedro Rodrigues", "Logística Global Lda", "938901234", "Aveiro"),
    ("Inês Oliveira", "HealthCare Digital", "965678901", "Setúbal"),
    ("André Sousa", "Energy Grid Systems", "919012345", "Évora"),
    ("Carolina Pereira", "CyberConsulting PT", "924567893", "Viseu"),
    ("Miguel Almeida", "Media Streaming Corp", "937890124", "Leiria"),
]


class HoneyDatabaseGenerator:
    """Generates realistic synthetic datasets with 5 watermarked 'living cells'."""

    def __init__(self, callback_host: str = "127.0.0.1", callback_port: int = 8080):
        self.callback_host = callback_host
        self.callback_port = callback_port
        self.registry: Dict[str, HoneyDatabaseDump] = {}
        self.active_canary_emails: Dict[str, Dict[str, Any]] = {}
        self.active_gps_keys: Dict[str, Dict[str, Any]] = {}

    def generate_customers_dump(
        self,
        session_id: str = "demo-session-001",
        record_count: int = 25,
        table_name: str = "customers",
    ) -> HoneyDatabaseDump:
        """Generate a realistic SQL and CSV dump with 5 armed living cell tokens."""
        now_iso = datetime.now(timezone.utc).isoformat()
        dump_id = f"dump_{session_id[:8]}_{int(datetime.now(timezone.utc).timestamp())}"
        watermark_str = f"WATERMARK-PICOAS-FORENSIC:{session_id}:{dump_id}:{now_iso}"
        watermark_hash = hashlib.sha256(watermark_str.encode("utf-8")).hexdigest()

        living_cells: List[LivingCellToken] = []

        # 1. Living Cell 1: Armed Honey Email (Monitored for Dark Web Leaks & Phishing)
        canary_email_1 = f"carlos.canary+leak_{session_id[:6]}@alert.picoas-cloud.internal"
        living_cells.append(
            LivingCellToken(
                cell_id=f"cell_email_{dump_id}_1",
                token_type="CANARY_EMAIL",
                label="Lead Architect (Canary Email Trap)",
                token_value=canary_email_1,
                tracking_payload=f"https://{self.callback_host}:{self.callback_port}/api/v1/canary/email-alert?token={canary_email_1}&session={session_id}",
                description="Monitored decoy email address. If emailed or spammed on dark web, identifies leak origin.",
            )
        )
        self.active_canary_emails[canary_email_1] = {
            "session_id": session_id,
            "dump_id": dump_id,
            "created_at": now_iso,
        }

        # 2. Living Cell 2: Armed Honey Email 2 (Executive VIP)
        canary_email_2 = f"diretoria.executiva+leak_{session_id[:6]}@alert.picoas-cloud.internal"
        living_cells.append(
            LivingCellToken(
                cell_id=f"cell_email_{dump_id}_2",
                token_type="CANARY_EMAIL",
                label="Chief Financial Officer (Canary VIP Trap)",
                token_value=canary_email_2,
                tracking_payload=f"https://{self.callback_host}:{self.callback_port}/api/v1/canary/email-alert?token={canary_email_2}&session={session_id}",
                description="Executive honey email address for detecting targeted corporate spear-phishing.",
            )
        )
        self.active_canary_emails[canary_email_2] = {
            "session_id": session_id,
            "dump_id": dump_id,
            "created_at": now_iso,
        }

        # 3. Living Cell 3: API Key com GPS Lógico (Callback Canary)
        api_key_token = f"sk_live_picoas_gps_{session_id[:8]}_{watermark_hash[:8]}"
        gps_url = f"http://{self.callback_host}:{self.callback_port}/api/v1/validate_key?api_key={api_key_token}"
        living_cells.append(
            LivingCellToken(
                cell_id=f"cell_api_{dump_id}_3",
                token_type="CANARY_API_KEY",
                label="Stripe / Production API Key (Logical GPS Trap)",
                token_value=api_key_token,
                tracking_payload=gps_url,
                description="Fake live API key. When tested in attacker's local scripts, fires telemetry revealing attacker's real IP.",
            )
        )
        self.active_gps_keys[api_key_token] = {
            "session_id": session_id,
            "dump_id": dump_id,
            "created_at": now_iso,
            "label": "Production Payment Gateway API Key",
        }

        # 4. Living Cell 4: Second API Key with GPS Lógico (Internal Microservice)
        api_key_token_2 = f"sk_live_cloud_backend_gps_{session_id[:8]}"
        living_cells.append(
            LivingCellToken(
                cell_id=f"cell_api_{dump_id}_4",
                token_type="CANARY_API_KEY",
                label="Internal Microservice Secret Token",
                token_value=api_key_token_2,
                tracking_payload=f"http://{self.callback_host}:{self.callback_port}/api/v1/validate_key?api_key={api_key_token_2}",
                description="Secondary API token planted in customer metadata to detect multi-stage tool validation.",
            )
        )
        self.active_gps_keys[api_key_token_2] = {
            "session_id": session_id,
            "dump_id": dump_id,
            "created_at": now_iso,
            "label": "Internal Microservice Secret Token",
        }

        # 5. Living Cell 5: Cryptographic Forensic Watermark
        living_cells.append(
            LivingCellToken(
                cell_id=f"cell_watermark_{dump_id}_5",
                token_type="FORENSIC_WATERMARK",
                label="Cryptographic Provenance Watermark",
                token_value=watermark_hash,
                tracking_payload=watermark_str,
                description="SHA-256 digital provenance watermark proving legal attribution and exact exfiltration timestamp.",
            )
        )

        # Assemble Records
        records = []
        # Normal records
        for i in range(max(record_count - 5, 5)):
            name_idx = i % len(NAMES_POOL)
            name, company, phone, city = NAMES_POOL[name_idx]
            clean_name = name.lower().replace(" ", ".")
            records.append({
                "id": i + 1,
                "name": f"{name} {i+1}",
                "email": f"{clean_name}{i+1}@empresa-cliente.pt",
                "company": company,
                "phone": phone,
                "city": city,
                "api_key": f"sk_test_demo_{hashlib.md5(f'{i}'.encode()).hexdigest()[:16]}",
                "status": "ACTIVE",
            })

        # Inject the 5 Living Cells at deterministic positions
        armed_records = [
            {
                "id": len(records) + 1,
                "name": "Carlos M. Vasconcelos (Lead Arch)",
                "email": canary_email_1,
                "company": "Picoas Cloud Architecture",
                "phone": "+351 910 000 001",
                "city": "Lisboa",
                "api_key": api_key_token,
                "status": "PRIORITY_INTERNAL",
            },
            {
                "id": len(records) + 2,
                "name": "Dra. Helena Barreto (CFO)",
                "email": canary_email_2,
                "company": "Executive Finance Board",
                "phone": "+351 910 000 002",
                "city": "Porto",
                "api_key": api_key_token_2,
                "status": "EXECUTIVE",
            },
            {
                "id": len(records) + 3,
                "name": f"Auditoria Forense (Ref: {dump_id})",
                "email": f"audit_{session_id[:6]}@compliance.picoas.internal",
                "company": "Compliance & Security Office",
                "phone": "+351 910 000 003",
                "city": "Lisboa",
                "api_key": f"sk_audit_{watermark_hash[:16]}",
                "status": f"WATERMARKED_HASH:{watermark_hash[:16]}",
            },
        ]
        records.extend(armed_records)

        # Generate SQL Content
        sql_lines = [
            f"-- -------------------------------------------------------------",
            f"-- Database Dump: {table_name}",
            f"-- Dump ID: {dump_id}",
            f"-- Forensic Watermark: {watermark_hash}",
            f"-- Exported: {now_iso}",
            f"-- -------------------------------------------------------------",
            f"CREATE TABLE IF NOT EXISTS {table_name} (",
            f"  id INT PRIMARY KEY AUTO_INCREMENT,",
            f"  name VARCHAR(100) NOT NULL,",
            f"  email VARCHAR(150) UNIQUE NOT NULL,",
            f"  company VARCHAR(100),",
            f"  phone VARCHAR(20),",
            f"  city VARCHAR(50),",
            f"  api_key VARCHAR(100),",
            f"  status VARCHAR(50)",
            f");\n",
            f"INSERT INTO {table_name} (id, name, email, company, phone, city, api_key, status) VALUES",
        ]
        val_rows = []
        for r in records:
            val_rows.append(
                f"  ({r['id']}, '{r['name']}', '{r['email']}', '{r['company']}', '{r['phone']}', '{r['city']}', '{r['api_key']}', '{r['status']}')"
            )
        sql_lines.append(",\n".join(val_rows) + ";\n")
        sql_lines.append(f"-- END OF DUMP (Checksum: {watermark_hash})\n")
        sql_content = "\n".join(sql_lines)

        # Generate CSV Content
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "name", "email", "company", "phone", "city", "api_key", "status"])
        writer.writeheader()
        for r in records:
            writer.writerow(r)
        csv_content = output.getvalue()

        dump = HoneyDatabaseDump(
            dump_id=dump_id,
            generated_at=now_iso,
            session_id=session_id,
            table_name=table_name,
            total_records=len(records),
            living_cells=living_cells,
            watermark_hash=watermark_hash,
            sql_content=sql_content,
            csv_content=csv_content,
        )

        self.registry[dump_id] = dump
        return dump

    def verify_exfiltrated_leak(self, text_sample: str) -> Optional[Dict[str, Any]]:
        """Verify if a sample text/data matches any living cell or watermark."""
        for dump_id, dump in self.registry.items():
            if dump.watermark_hash in text_sample:
                return {
                    "matched": True,
                    "dump_id": dump_id,
                    "session_id": dump.session_id,
                    "generated_at": dump.generated_at,
                    "type": "FORENSIC_WATERMARK_MATCH",
                }
            for cell in dump.living_cells:
                if cell.token_value in text_sample:
                    return {
                        "matched": True,
                        "dump_id": dump_id,
                        "session_id": dump.session_id,
                        "generated_at": dump.generated_at,
                        "type": cell.token_type,
                        "token_value": cell.token_value,
                        "label": cell.label,
                    }
        return None


HONEY_DB_GENERATOR = HoneyDatabaseGenerator()
