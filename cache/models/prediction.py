"""
Pydantic models for AI predictions received from the prediction feed.

Designed for high resilience and extensibility:
- extra="allow": accepts any additional metadata sent by the AI without failing
- Dual-format parser: supports both direct predictions list and the Gemini AI
  feed format (cache_manager_feed.json with deployments & processed_events)
- Flexible date parser: handles ISO 8601 strings, timestamps, and varied timezone offsets
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
import dateutil.parser

logger = logging.getLogger(__name__)


def _parse_flexible_datetime(v: Any) -> datetime:
    """Parses datetime from ISO string, timestamp, or datetime object, normalized to UTC."""
    if isinstance(v, datetime):
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(v, str):
        try:
            dt = dateutil.parser.isoparse(v)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    logger.warning("Unrecognized datetime format '%s', defaulting to now UTC", v)
    return datetime.now(timezone.utc)


class ServicePrediction(BaseModel):
    """A specific service/platform predicted to have high demand."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(default="general_service", description="Service category")
    platforms: list[str] = Field(default_factory=list, description="Specific platforms")
    priority: float = Field(default=0.8, ge=0.0, le=1.0, description="Priority score 0-1")
    cache_size_mb: int = Field(default=256, description="Suggested cache allocation in MB")
    content_keys: list[str] = Field(
        default_factory=list,
        description="Specific cache keys/routes to pre-warm"
    )


class EventPrediction(BaseModel):
    """A single event prediction from the AI module."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., description="Unique prediction ID")
    region: str = Field(..., description="Cloud region (e.g. 'eu-west-1', 'eu-south-1')")
    event_type: str = Field(default="general_event", description="Type of event")
    event_name: str = Field(default="Predicted Peak Event", description="Human-readable event name")
    event_start: datetime = Field(..., description="When the event starts (UTC)")
    lead_time_minutes: int = Field(
        default=60,
        description="How many minutes before event_start to begin warming"
    )
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="AI confidence score")
    expected_load_multiplier: float = Field(
        default=2.0,
        description="Expected traffic increase multiplier"
    )
    services: list[ServicePrediction] = Field(
        default_factory=list,
        description="Services to prioritize in cache"
    )

    @field_validator("event_start", mode="before")
    @classmethod
    def _validate_event_start(cls, v: Any) -> datetime:
        return _parse_flexible_datetime(v)

    @property
    def warm_at(self) -> datetime:
        """UTC datetime when cache warming should begin."""
        return self.event_start - timedelta(minutes=self.lead_time_minutes)

    @property
    def ttl_seconds(self) -> int:
        """Cache TTL — keep hot until 90 min after event start."""
        from config import settings
        duration = timedelta(minutes=self.lead_time_minutes + 90)
        return max(settings.default_ttl_seconds, int(duration.total_seconds()))


class PredictionFile(BaseModel):
    """Root schema of the JSON predictions loaded from the AI module."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the AI generated these predictions"
    )
    predictions: list[EventPrediction] = Field(default_factory=list)

    @field_validator("generated_at", mode="before")
    @classmethod
    def _validate_generated_at(cls, v: Any) -> datetime:
        return _parse_flexible_datetime(v)

    @classmethod
    def from_raw_json(cls, data: dict[str, Any]) -> "PredictionFile":
        """
        Intelligent loader that parses:
          1. Standard PredictionFile format (with 'predictions' list)
          2. Gemini AI / Scraper format (cache_manager_feed.json with 'deployments' and 'processed_events')
          3. Any extended JSON variant without breaking
        """
        # Case 1: Standard format
        if "predictions" in data and isinstance(data["predictions"], list):
            return cls.model_validate(data)

        # Case 2: Gemini AI / cache_manager_feed format from scraper-ai
        if "deployments" in data or "processed_events" in data:
            return cls._from_gemini_feed(data)

        # Case 3: Empty or unknown structure - gracefully return empty predictions
        logger.warning("Unrecognized prediction JSON shape, returning empty prediction batch")
        return cls(generated_at=datetime.now(timezone.utc), predictions=[])

    @classmethod
    def _from_gemini_feed(cls, data: dict[str, Any]) -> "PredictionFile":
        """Adapts cache_manager_feed.json from scraper-ai into normalized PredictionFile."""
        generated_at = _parse_flexible_datetime(data.get("timestamp_utc", datetime.now(timezone.utc)))
        instructions = data.get("cache_manager_instructions", {})
        default_lead_time = int(instructions.get("lead_time_minutes", 30))

        deployments = data.get("deployments", {})
        processed_events = data.get("processed_events", [])

        adapted_predictions: list[EventPrediction] = []

        if deployments:
            for dep_name, dep_data in deployments.items():
                aws_region = dep_data.get("aws_region") or dep_name
                multiplier = float(dep_data.get("traffic_multiplier", 1.5))
                cache_dir = dep_data.get("cache_directive", {})
                pre_warm_routes = cache_dir.get("pre_warm_routes", [])

                # Identify events covering this zone / deployment
                zone_events = [
                    ev for ev in processed_events
                    if ev.get("country") in dep_data.get("covered_countries", [])
                ]
                if not zone_events:
                    zone_events = processed_events

                if not zone_events:
                    # Synthesize an event from deployment directive
                    start_time = datetime.now(timezone.utc) + timedelta(minutes=default_lead_time)
                    svc = ServicePrediction(
                        name=dep_data.get("function", "api_service"),
                        platforms=[dep_name],
                        priority=1.0,
                        cache_size_mb=384,
                        content_keys=pre_warm_routes,
                    )
                    adapted_predictions.append(
                        EventPrediction(
                            id=f"feed-{dep_name}",
                            region=aws_region,
                            event_type="zone_traffic_surge",
                            event_name=f"Traffic Surge on {dep_name.upper()} ({aws_region})",
                            event_start=start_time,
                            lead_time_minutes=default_lead_time,
                            confidence=0.90,
                            expected_load_multiplier=multiplier,
                            services=[svc],
                            **{"raw_deployment_data": dep_data}
                        )
                    )
                else:
                    for idx, ev in enumerate(zone_events):
                        ev_start = _parse_flexible_datetime(ev.get("start_utc", ev.get("start", datetime.now(timezone.utc))))
                        category = ev.get("category", "event")
                        confidence = float(ev.get("confidence", 0.85))
                        routes = ev.get("pre_warm_routes", pre_warm_routes)

                        svc = ServicePrediction(
                            name=category,
                            platforms=[ev.get("country", dep_name)],
                            priority=min(1.0, float(ev.get("adjusted_effect", 0.8))),
                            cache_size_mb=384 if multiplier >= 1.5 else 256,
                            content_keys=routes,
                        )

                        adapted_predictions.append(
                            EventPrediction(
                                id=f"feed-{dep_name}-{ev.get('id', idx)}",
                                region=aws_region,
                                event_type=category,
                                event_name=ev.get("event_description", f"Event in {dep_name}"),
                                event_start=ev_start,
                                lead_time_minutes=default_lead_time,
                                confidence=confidence,
                                expected_load_multiplier=multiplier,
                                services=[svc],
                                **{
                                    "reasoning": ev.get("reasoning", ""),
                                    "traffic_pattern": ev.get("traffic_pattern", ""),
                                    "cache_strategy": ev.get("cache_strategy", ""),
                                    "target_concurrency": dep_data.get("target_lambda_concurrency"),
                                    "analyzed_by": ev.get("analyzed_by", "ai"),
                                }
                            )
                        )
        else:
            # If only processed_events are present
            for idx, ev in enumerate(processed_events):
                ev_start = _parse_flexible_datetime(ev.get("start_utc", datetime.now(timezone.utc)))
                country = ev.get("country", "GLOBAL")
                region_map = {"PT": "eu-west-1", "ES": "eu-west-1", "GB": "eu-west-2", "DE": "eu-central-1", "FR": "eu-west-3"}
                region = region_map.get(country, "eu-west-1")

                svc = ServicePrediction(
                    name=ev.get("category", "event"),
                    platforms=[country],
                    priority=0.9,
                    cache_size_mb=256,
                    content_keys=ev.get("pre_warm_routes", []),
                )
                adapted_predictions.append(
                    EventPrediction(
                        id=f"event-{idx}",
                        region=region,
                        event_type=ev.get("category", "event"),
                        event_name=ev.get("event_description", "Event"),
                        event_start=ev_start,
                        lead_time_minutes=default_lead_time,
                        confidence=float(ev.get("confidence", 0.85)),
                        expected_load_multiplier=float(ev.get("adjusted_effect", 2.0)),
                        services=[svc],
                    )
                )

        return cls(
            generated_at=generated_at,
            predictions=adapted_predictions,
            **{"ai_status": data.get("ai_status", {}), "generator_version": data.get("generator_version", "")}
        )
