"""
FastAPI routes for the Cache Intelligence Module.
"""
from __future__ import annotations
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from services.metrics import compute_metrics

logger = logging.getLogger(__name__)

router = APIRouter()

# These are set by main.py after startup
_warmer = None
_watcher = None
_planner = None


def set_dependencies(warmer, watcher, planner):
    global _warmer, _watcher, _planner
    _warmer = warmer
    _watcher = watcher
    _planner = planner


# ─── Health & Status ────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


@router.get("/status")
async def status():
    plan = _warmer.current_plan if _warmer else None
    predictions = _watcher.current_predictions if _watcher else None

    region_summary = {}
    if plan:
        for region, plans in plan.region_plans.items():
            region_summary[region] = [
                {
                    "event": p.event_name,
                    "status": p.status.value,
                    "warm_at": p.warm_at.isoformat(),
                    "event_start": p.event_start.isoformat(),
                    "entries": len(p.entries),
                    "allocated_mb": p.total_allocated_mb,
                    "hit_rate": p.overall_hit_rate,
                }
                for p in plans
            ]

    return {
        "service": "cache-intelligence",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "predictions_loaded": predictions is not None,
        "predictions_generated_at": predictions.generated_at.isoformat() if predictions else None,
        "total_predictions": len(predictions.predictions) if predictions else 0,
        "regions": region_summary,
    }


# ─── Predictions ────────────────────────────────────────────────────────────

@router.get("/predictions")
async def get_predictions():
    predictions = _watcher.current_predictions if _watcher else None
    if not predictions:
        return {"predictions": [], "message": "No predictions loaded yet"}

    return {
        "generated_at": predictions.generated_at.isoformat(),
        "count": len(predictions.predictions),
        "predictions": [
            {
                "id": p.id,
                "region": p.region,
                "event_type": p.event_type,
                "event_name": p.event_name,
                "event_start": p.event_start.isoformat(),
                "warm_at": p.warm_at.isoformat(),
                "confidence": p.confidence,
                "expected_load_multiplier": p.expected_load_multiplier,
                "services": [
                    {"name": s.name, "platforms": s.platforms, "priority": s.priority}
                    for s in p.services
                ],
            }
            for p in predictions.predictions
        ],
    }


# ─── Cache Plan ─────────────────────────────────────────────────────────────

@router.get("/plan")
async def get_plan():
    plan = _warmer.current_plan if _warmer else None
    if not plan:
        return {"plan": None, "message": "No cache plan active"}

    return {
        "generated_at": plan.generated_at.isoformat(),
        "regions": {
            region: [
                {
                    "event_name": p.event_name,
                    "prediction_id": p.prediction_id,
                    "status": p.status.value,
                    "warm_at": p.warm_at.isoformat(),
                    "event_start": p.event_start.isoformat(),
                    "warmed_at": p.warmed_at.isoformat() if p.warmed_at else None,
                    "total_allocated_mb": p.total_allocated_mb,
                    "entries": [
                        {
                            "cache_key": e.cache_key,
                            "service": e.service_name,
                            "platform": e.platform,
                            "priority": e.priority,
                            "ttl_seconds": e.ttl_seconds,
                            "hit_rate": e.hit_rate,
                            "hits": e.hit_count,
                            "misses": e.miss_count,
                        }
                        for e in sorted(p.entries, key=lambda e: e.priority, reverse=True)
                    ],
                }
                for p in plans
            ]
            for region, plans in plan.region_plans.items()
        },
    }


# ─── Metrics ────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics():
    plan = _warmer.current_plan if _warmer else None
    if not plan:
        return {"metrics": {}, "message": "No plan active"}
    return compute_metrics(plan)


# ─── Cache Control ──────────────────────────────────────────────────────────

@router.post("/warm/{region}")
async def force_warm(region: str):
    """Force immediate cache warming for a region."""
    if not _warmer:
        raise HTTPException(503, "Warmer not initialised")
    count = await _warmer.force_warm_region(region)
    return {
        "region": region,
        "plans_warmed": count,
        "message": f"Forced warming of {count} plan(s) for region '{region}'",
    }


@router.delete("/cache/{region}")
async def flush_region(region: str):
    """Flush all cache entries for a region."""
    if not _warmer:
        raise HTTPException(503, "Warmer not initialised")
    deleted = await _warmer.flush_region(region)
    return {
        "region": region,
        "keys_deleted": deleted,
        "message": f"Flushed {deleted} keys from region '{region}'",
    }


# ─── Simulate hit/miss (for demo/testing) ───────────────────────────────────

@router.post("/simulate/hit")
async def simulate_hit(cache_key: str):
    """Simulate a cache hit on a key (for demo purposes)."""
    if _warmer:
        await _warmer.record_hit(cache_key)
    return {"cache_key": cache_key, "event": "hit"}


@router.post("/simulate/miss")
async def simulate_miss(cache_key: str):
    """Simulate a cache miss on a key (for demo purposes)."""
    if _warmer:
        await _warmer.record_miss(cache_key)
    return {"cache_key": cache_key, "event": "miss"}
