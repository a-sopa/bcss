"""
Cache Warmer — executes the warming plan against Redis.

For each RegionCachePlan that is due to be warmed, this service:
  1. Checks if warm_at time has been reached
  2. Writes priority-scored entries into Redis with appropriate TTLs
  3. Updates plan status (PENDING → WARMING → HOT)

In a real system, the "value" stored would be pre-fetched content
(e.g. CDN URLs resolved, API responses cached). Here we store metadata
about what should be served from edge/CDN, which the network layer
can use to route and prioritise.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from models.cache_plan import CachePlan, RegionCachePlan, CacheEntry, WarmingStatus
from config import settings

logger = logging.getLogger(__name__)


def _build_redis_value(entry: CacheEntry, event_name: str) -> dict:
    """
    Build the value stored in Redis for a cache entry.
    Contains routing hints for the network/CDN layer.
    """
    return {
        "service": entry.service_name,
        "platform": entry.platform,
        "region": entry.region,
        "priority": entry.priority,
        "event": event_name,
        "warmed_at": datetime.now(timezone.utc).isoformat(),
        "ttl_seconds": entry.ttl_seconds,
    }


class CacheWarmer:
    """
    Async cache warmer that connects to Redis and pre-warms entries
    based on the schedule in the CachePlan.
    """

    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._plan: CachePlan | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        """Create async Redis connection."""
        self._redis = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password,
            decode_responses=True,
        )
        await self._redis.ping()
        logger.info(f"✅ Redis connected at {settings.redis_host}:{settings.redis_port}")

    async def disconnect(self):
        if self._redis:
            await self._redis.aclose()

    def update_plan(self, plan: CachePlan):
        """Update the active cache plan (called by planner)."""
        self._plan = plan

    @property
    def current_plan(self) -> CachePlan | None:
        return self._plan

    async def tick(self):
        """
        Called periodically by the scheduler.
        Checks for plans that are due to be warmed and executes them.
        """
        if not self._plan or not self._redis:
            return

        now = datetime.now(timezone.utc)

        for region, region_plans in self._plan.region_plans.items():
            for rplan in region_plans:
                # Ensure warm_at is timezone-aware
                warm_at = rplan.warm_at
                if warm_at.tzinfo is None:
                    warm_at = warm_at.replace(tzinfo=timezone.utc)
                
                if rplan.status == WarmingStatus.PENDING and now >= warm_at:
                    await self._warm_region_plan(rplan)
                elif rplan.status == WarmingStatus.HOT:
                    # Ensure event_start is timezone-aware
                    event_start = rplan.event_start
                    if event_start.tzinfo is None:
                        event_start = event_start.replace(tzinfo=timezone.utc)
                    await self._check_cooling(rplan, now, event_start)

    async def _warm_region_plan(self, rplan: RegionCachePlan):
        """Pre-warm all entries in a region plan."""
        rplan.status = WarmingStatus.WARMING
        logger.info(f"🔥 Warming cache [{rplan.region}] for '{rplan.event_name}' "
                    f"({len(rplan.entries)} entries)")

        pipeline = self._redis.pipeline()
        warmed = 0
        failed = 0

        for entry in sorted(rplan.entries, key=lambda e: e.priority, reverse=True):
            try:
                value = _build_redis_value(entry, rplan.event_name)
                # Store as Redis hash for rich metadata
                await self._redis.hset(entry.cache_key, mapping={
                    k: str(v) for k, v in value.items()
                })
                await self._redis.expire(entry.cache_key, entry.ttl_seconds)
                warmed += 1
            except Exception as exc:
                logger.error(f"Failed to warm {entry.cache_key}: {exc}")
                failed += 1

        rplan.status = WarmingStatus.HOT
        rplan.warmed_at = datetime.now(timezone.utc)

        logger.info(
            f"✅ Cache HOT [{rplan.region}] '{rplan.event_name}' | "
            f"warmed={warmed} failed={failed} | "
            f"{rplan.total_allocated_mb:.1f} MB allocated"
        )

    async def _check_cooling(self, rplan: RegionCachePlan, now: datetime, event_start: datetime):
        """Mark a plan as cooling 90 minutes after event start."""
        from datetime import timedelta
        if now > event_start + timedelta(minutes=90):
            rplan.status = WarmingStatus.COOLING
            logger.info(f"❄️  Cooling [{rplan.region}] '{rplan.event_name}'")

    async def record_hit(self, cache_key: str):
        """Record a cache hit for metrics."""
        if not self._plan:
            return
        for plans in self._plan.region_plans.values():
            for rplan in plans:
                for entry in rplan.entries:
                    if entry.cache_key == cache_key:
                        entry.hit_count += 1
                        return

    async def record_miss(self, cache_key: str):
        """Record a cache miss for metrics."""
        if not self._plan:
            return
        for plans in self._plan.region_plans.values():
            for rplan in plans:
                for entry in rplan.entries:
                    if entry.cache_key == cache_key:
                        entry.miss_count += 1
                        return

    async def flush_region(self, region: str) -> int:
        """Remove all cache keys for a given region. Returns count deleted."""
        if not self._redis:
            return 0
        pattern = f"cache:{region}:*"
        keys = await self._redis.keys(pattern)
        if keys:
            await self._redis.delete(*keys)
        logger.info(f"🗑️  Flushed {len(keys)} keys from region [{region}]")
        return len(keys)

    async def force_warm_region(self, region: str) -> int:
        """Force immediate warming for all PENDING plans in a region."""
        if not self._plan or region not in self._plan.region_plans:
            return 0
        count = 0
        for rplan in self._plan.region_plans[region]:
            if rplan.status == WarmingStatus.PENDING:
                await self._warm_region_plan(rplan)
                count += 1
        return count
