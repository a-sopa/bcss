"""
Cache plan models — the output of the Cache Planner.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class WarmingStatus(str, Enum):
    PENDING = "pending"       # Scheduled, not yet started
    WARMING = "warming"       # Currently pre-warming
    HOT = "hot"               # Warmed and active
    COOLING = "cooling"       # Event passed, TTL counting down
    EXPIRED = "expired"       # TTL elapsed, cache evicted
    FAILED = "failed"         # Warming attempt failed


class CacheEntry(BaseModel):
    """A single planned cache entry for a service/key."""
    cache_key: str = Field(..., description="Redis key")
    service_name: str
    platform: str
    region: str
    priority: float
    ttl_seconds: int
    size_bytes: int = 0
    hit_count: int = 0
    miss_count: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return round(self.hit_count / total, 4) if total > 0 else 0.0


class RegionCachePlan(BaseModel):
    """Cache warming plan for a single region."""
    region: str
    prediction_id: str
    event_name: str
    event_start: datetime
    warm_at: datetime
    status: WarmingStatus = WarmingStatus.PENDING
    entries: list[CacheEntry] = Field(default_factory=list)
    total_allocated_mb: float = 0.0
    warmed_at: datetime | None = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_hits(self) -> int:
        return sum(e.hit_count for e in self.entries)

    @property
    def total_misses(self) -> int:
        return sum(e.miss_count for e in self.entries)

    @property
    def overall_hit_rate(self) -> float:
        total = self.total_hits + self.total_misses
        return self.total_hits / total if total > 0 else 0.0


class CachePlan(BaseModel):
    """Full cache plan across all regions."""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    region_plans: dict[str, list[RegionCachePlan]] = Field(default_factory=dict)

    def get_active_plans(self) -> list[RegionCachePlan]:
        """Return plans that are currently hot or warming."""
        active = []
        for plans in self.region_plans.values():
            active.extend(
                p for p in plans
                if p.status in (WarmingStatus.WARMING, WarmingStatus.HOT)
            )
        return active
