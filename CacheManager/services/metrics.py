"""
Metrics service — aggregates cache hit/miss stats per region and service.
"""
from __future__ import annotations
from datetime import datetime
from dataclasses import dataclass, field

from models.cache_plan import CachePlan, WarmingStatus


@dataclass
class ServiceMetrics:
    service: str
    platform: str
    hits: int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total > 0 else 0.0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses


@dataclass
class RegionMetrics:
    region: str
    active_events: list[str] = field(default_factory=list)
    total_hits: int = 0
    total_misses: int = 0
    allocated_mb: float = 0.0
    services: list[ServiceMetrics] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        total = self.total_hits + self.total_misses
        return round(self.total_hits / total, 4) if total > 0 else 0.0


def compute_metrics(plan: CachePlan) -> dict:
    """
    Compute metrics summary from the current cache plan.
    Returns a dict suitable for JSON serialisation.
    """
    result: dict[str, RegionMetrics] = {}

    for region, region_plans in plan.region_plans.items():
        rm = RegionMetrics(region=region)

        for rplan in region_plans:
            if rplan.status in (WarmingStatus.HOT, WarmingStatus.WARMING):
                rm.active_events.append(rplan.event_name)
                rm.allocated_mb += rplan.total_allocated_mb

            for entry in rplan.entries:
                rm.total_hits += entry.hit_count
                rm.total_misses += entry.miss_count

                svc_m = next(
                    (s for s in rm.services
                     if s.service == entry.service_name and s.platform == entry.platform),
                    None
                )
                if svc_m is None:
                    svc_m = ServiceMetrics(
                        service=entry.service_name, platform=entry.platform
                    )
                    rm.services.append(svc_m)
                svc_m.hits += entry.hit_count
                svc_m.misses += entry.miss_count

        result[region] = rm

    return {
        "computed_at": datetime.utcnow().isoformat() + "Z",
        "regions": {
            region: {
                "region": rm.region,
                "hit_rate": rm.hit_rate,
                "total_hits": rm.total_hits,
                "total_misses": rm.total_misses,
                "allocated_mb": rm.allocated_mb,
                "active_events": rm.active_events,
                "services": [
                    {
                        "service": s.service,
                        "platform": s.platform,
                        "hit_rate": s.hit_rate,
                        "total_requests": s.total_requests,
                    }
                    for s in sorted(rm.services, key=lambda s: s.hit_rate, reverse=True)
                ],
            }
            for region, rm in result.items()
        },
    }
