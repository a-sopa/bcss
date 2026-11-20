"""AI Threat Intelligence and Behavioral Analysis Engine."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from cloud_honeypot_ai.ai.bot_classifier import BOT_CLASSIFIER, AttackerProfile
from cloud_honeypot_ai.ai.mitre_attack import MITRE_MAPPER, MitreTechnique
from cloud_honeypot_ai.core.session import HoneypotSession

logger = logging.getLogger("honeypot.ai.analyzer")


@dataclass
class ThreatReport:
    """Comprehensive AI Threat Intelligence assessment."""
    session_id: str
    analyzed_at: str
    attacker_ip: str
    country: str
    city: str
    asn: str
    protocol: str
    profile: AttackerProfile
    mitre_techniques: List[MitreTechnique]
    risk_score: int  # 0 to 100
    threat_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    canary_breaches: List[str]
    iocs: Dict[str, List[str]]
    executive_summary: str
    recommended_defense: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "analyzed_at": self.analyzed_at,
            "attacker_ip": self.attacker_ip,
            "country": self.country,
            "city": self.city,
            "asn": self.asn,
            "protocol": self.protocol,
            "profile": asdict(self.profile),
            "mitre_techniques": [asdict(t) for t in self.mitre_techniques],
            "risk_score": self.risk_score,
            "threat_level": self.threat_level,
            "canary_breaches": self.canary_breaches,
            "iocs": self.iocs,
            "executive_summary": self.executive_summary,
            "recommended_defense": self.recommended_defense,
        }


class ThreatAnalyzer:
    """AI Behavioral Analysis and Threat Scoring Engine."""

    def analyze_session(self, session: HoneypotSession) -> ThreatReport:
        """Perform full AI threat intelligence assessment on a honeypot session."""
        auth_dicts = [asdict(a) for a in session.auth_attempts]
        cmd_dicts = [asdict(c) for c in session.commands]
        geo = session.geo or {}

        # 1. Profile attacker persona (Botnet vs Human vs APT)
        profile = BOT_CLASSIFIER.profile_session(
            auth_attempts=auth_dicts,
            commands=cmd_dicts,
            duration_seconds=session.duration_seconds(),
        )

        # 2. Map MITRE ATT&CK techniques
        mitre_techniques = MITRE_MAPPER.map_commands(cmd_dicts)
        auth_technique = MITRE_MAPPER.map_auth(len(auth_dicts))
        if auth_technique and not any(t.technique_id == "T1110.001" for t in mitre_techniques):
            mitre_techniques.append(auth_technique)

        # 3. Calculate Threat Score (0 to 100)
        score = 0

        # Baseline connection score
        score += 15

        # Brute force score
        if len(auth_dicts) >= 1:
            score += min(len(auth_dicts) * 5, 25)

        # Authentication success score (gained shell access)
        if session.authenticated:
            score += 20

        # Severity additions based on MITRE techniques
        for t in mitre_techniques:
            if t.severity == "CRITICAL":
                score += 30
            elif t.severity == "HIGH":
                score += 20
            elif t.severity == "MEDIUM":
                score += 10
            elif t.severity == "LOW":
                score += 5

        # Canary breaches (stolen credentials)
        if session.canary_alerts:
            score += 35

        score = min(max(score, 0), 100)

        # Classify Threat Level
        if score >= 85:
            threat_level = "CRITICAL"
        elif score >= 65:
            threat_level = "HIGH"
        elif score >= 40:
            threat_level = "MEDIUM"
        else:
            threat_level = "LOW"

        # Update session metadata
        session.risk_score = score
        session.threat_level = threat_level

        # 4. Extract IoCs (Indicators of Compromise)
        passwords_tried = list({a.password for a in session.auth_attempts})
        users_tried = list({a.username for a in session.auth_attempts})
        dropped_urls = []
        for c in session.commands:
            if "http://" in c.command or "https://" in c.command:
                words = c.command.split()
                for w in words:
                    if w.startswith("http://") or w.startswith("https://"):
                        dropped_urls.append(w)

        iocs = {
            "attacker_ips": [session.remote_ip],
            "usernames_attempted": users_tried,
            "passwords_attempted": passwords_tried,
            "payload_urls": list(set(dropped_urls)),
        }

        # 5. Generate Natural Language AI Executive Summary
        country_name = geo.get("country", "Unknown Country")
        city_name = geo.get("city", "Unknown City")
        asn_name = geo.get("asn", "Unknown ASN")

        summary = (
            f"Detected an active {profile.classification} security incident originating from "
            f"{session.remote_ip} ({city_name}, {country_name} - {asn_name}) using {session.protocol}.\n"
            f"The adversary conducted {len(session.auth_attempts)} credential verification attempts "
            f"and executed {len(session.commands)} reconnaissance and exploitation commands. "
        )

        if session.canary_alerts:
            summary += (
                f"CRITICAL ALERT: The attacker accessed honey-tokens ({', '.join(session.canary_alerts)}), "
                "indicating active credential harvesting intended for cloud infrastructure compromise."
            )
        elif session.authenticated:
            summary += "The attacker successfully bypassed authentication using known weak credentials and interacted with the decoy shell."
        else:
            summary += "The attacker probed the perimeter without gaining full interactive access."

        # 6. Prescribe Recommended Cloud Defense Actions
        recommendations = [
            f"Block IP {session.remote_ip} at cloud VPC edge using Network ACLs (NACL) to drop malicious packets before EC2 compute.",
            f"Add {session.remote_ip} to AWS Security Group ingress blacklists.",
            "Deploy Cloudflare WAF or AWS WAF rate-limiting rule to mitigate brute-force botnets.",
        ]
        if session.canary_alerts:
            recommendations.append("Rotate any production AWS IAM keys and database credentials that resemble the canary tokens.")
        if dropped_urls:
            recommendations.append(f"Block outbound egress connections to payload drop domain(s): {', '.join(dropped_urls)}")

        return ThreatReport(
            session_id=session.session_id,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            attacker_ip=session.remote_ip,
            country=country_name,
            city=city_name,
            asn=asn_name,
            protocol=session.protocol,
            profile=profile,
            mitre_techniques=mitre_techniques,
            risk_score=score,
            threat_level=threat_level,
            canary_breaches=session.canary_alerts,
            iocs=iocs,
            executive_summary=summary,
            recommended_defense=recommendations,
        )


THREAT_ANALYZER = ThreatAnalyzer()
