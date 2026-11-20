"""Logical GPS Canary API Key Tracker.

Captures and de-anonymizes attackers when they test stolen API keys
in local scripts, extracting their real public IP and client fingerprints.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from cloud_honeypot_ai.core.geoip import DEFAULT_RESOLVER

logger = logging.getLogger("honeypot.deception.gps")


@dataclass
class GpsTriggerAlert:
    """An active de-anonymization alert triggered by testing a canary API key."""
    alert_id: str
    triggered_at: str
    canary_key: str
    source_session_id: str
    attacker_real_ip: str
    country: str
    city: str
    asn: str
    user_agent: str
    request_headers: Dict[str, str]
    revealed_vpn_bypass: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CanaryApiGpsTracker:
    """Tracks and registers GPS canary API key executions."""

    def __init__(self):
        self.triggers: List[GpsTriggerAlert] = []
        self._key_registry: Dict[str, Dict[str, Any]] = {}

    def register_key(self, api_key: str, origin_session_id: str, label: str = "Decoy API Key") -> None:
        """Register a generated canary key into tracking system."""
        self._key_registry[api_key] = {
            "origin_session_id": origin_session_id,
            "label": label,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

    def record_trigger(
        self,
        api_key: str,
        client_ip: str,
        user_agent: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> GpsTriggerAlert:
        """Handle execution of canary key and record de-anonymized attacker info."""
        now_iso = datetime.now(timezone.utc).isoformat()
        alert_id = f"gps_alert_{len(self.triggers) + 1}_{int(datetime.now(timezone.utc).timestamp())}"

        # Resolve GeoIP of the machine running the validation script
        geo = DEFAULT_RESOLVER.resolve(client_ip)

        # Extract session origin from registered metadata or key string
        metadata = self._key_registry.get(api_key, {})
        source_session = metadata.get("origin_session_id", "unknown")
        if source_session == "unknown" and "_gps_" in api_key:
            parts = api_key.split("_gps_")
            if len(parts) > 1:
                source_session = parts[1].split("_")[0]

        alert = GpsTriggerAlert(
            alert_id=alert_id,
            triggered_at=now_iso,
            canary_key=api_key,
            source_session_id=source_session,
            attacker_real_ip=client_ip,
            country=geo.country,
            city=geo.city,
            asn=geo.asn,
            user_agent=user_agent,
            request_headers=headers or {},
            revealed_vpn_bypass=not geo.is_private,
        )

        self.triggers.append(alert)
        logger.warning(
            "🚨 LOGICAL GPS TRIGGERED! Stolen API Key '%s' tested from IP %s (%s, %s - %s)",
            api_key[:18] + "...",
            client_ip,
            geo.city,
            geo.country,
            geo.asn,
        )
        return alert

    def all_triggers(self) -> List[GpsTriggerAlert]:
        return list(self.triggers)


CANARY_GPS_TRACKER = CanaryApiGpsTracker()
