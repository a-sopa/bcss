"""
Cache Planner — converts AI predictions into a concrete Redis cache warming plan.

Priority scoring formula:
  score = confidence × load_multiplier × service_priority × time_urgency_factor

Higher score → more cache space allocated, warmed first.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta

from models.prediction import PredictionFile, EventPrediction, ServicePrediction
from models.cache_plan import CachePlan, RegionCachePlan, CacheEntry, WarmingStatus
from config import settings

logger = logging.getLogger(__name__)


def _time_urgency(event: EventPrediction) -> float:
    """
    Returns a multiplier 0.5–2.0 based on how soon the event starts.
    Events starting in <30 min get max urgency (2.0).
    Events >24h away get min urgency (0.5).
    """
    now = datetime.now(timezone.utc)
    # Ensure event_start is timezone-aware
    event_start = event.event_start
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)
    
    minutes_until = (event_start - now).total_seconds() / 60
    if minutes_until <= 0:
        return 0.1   # Already started, low urgency for warming
    elif minutes_until < 30:
        return 2.0
    elif minutes_until < 120:
        return 1.5
    elif minutes_until < 360:
        return 1.2
    elif minutes_until < 1440:
        return 1.0
    else:
        return 0.5


def _make_cache_key(region: str, event_id: str, service: str, platform: str) -> str:
    """Generate a deterministic Redis cache key."""
    return f"cache:{region}:{event_id}:{service}:{platform.lower().replace(' ', '_')}"


def _score_service(event: EventPrediction, svc: ServicePrediction) -> float:
    """Composite priority score for a service within an event."""
    urgency = _time_urgency(event)
    return event.confidence * event.expected_load_multiplier * svc.priority * urgency


class CachePlanner:
    """
    Builds a CachePlan from a PredictionFile.
    
    Allocates cache budget per region, scores services by priority,
    and generates CacheEntry objects ready for warming.
    """

    def build_plan(self, predictions: PredictionFile) -> CachePlan:
        """Convert AI predictions into a full cache warming plan."""
        plan = CachePlan()

        for event in predictions.predictions:
            region = event.region
            if region not in plan.region_plans:
                plan.region_plans[region] = []

            # Ensure event_start is timezone-aware
            event_start = event.event_start
            if event_start.tzinfo is None:
                event_start = event_start.replace(tzinfo=timezone.utc)
            
            warm_at = event.warm_at
            if warm_at.tzinfo is None:
                warm_at = warm_at.replace(tzinfo=timezone.utc)

            region_plan = RegionCachePlan(
                region=region,
                prediction_id=event.id,
                event_name=event.event_name,
                event_start=event_start,
                warm_at=warm_at,
                status=WarmingStatus.PENDING,
            )

            # Score and sort services
            scored_services = sorted(
                [(svc, _score_service(event, svc)) for svc in event.services],
                key=lambda x: x[1],
                reverse=True,
            )

            total_mb = 0.0
            for svc, score in scored_services:
                platforms = svc.platforms if svc.platforms else [svc.name]
                for platform in platforms:
                    allocated_mb = min(
                        svc.cache_size_mb / max(len(platforms), 1),
                        settings.max_cache_size_mb_per_region - total_mb,
                    )
                    if allocated_mb <= 0:
                        logger.warning(
                            f"[{region}] Cache budget exhausted for {event.event_name}"
                        )
                        break

                    key = _make_cache_key(region, event.id, svc.name, platform)
                    entry = CacheEntry(
                        cache_key=key,
                        service_name=svc.name,
                        platform=platform,
                        region=region,
                        priority=round(score, 4),
                        ttl_seconds=event.ttl_seconds,
                        size_bytes=int(allocated_mb * 1024 * 1024),
                    )
                    region_plan.entries.append(entry)
                    total_mb += allocated_mb

            region_plan.total_allocated_mb = round(total_mb, 2)
            plan.region_plans[region].append(region_plan)

            logger.info(
                f"📋 Planned [{region}] {event.event_name} | "
                f"warm at {region_plan.warm_at.isoformat()} | "
                f"{len(region_plan.entries)} entries | "
                f"{total_mb:.1f} MB"
            )

        return plan
