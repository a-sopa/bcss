"""
Cache Intelligence Module — Entry Point

Starts:
  - FastAPI REST API (port 8001)
  - Background scheduler that:
      • polls the predictions JSON file (from AI module)
      • triggers cache planning when new predictions arrive
      • ticks the cache warmer every 30s
"""
from __future__ import annotations
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rich.logging import RichHandler

from config import settings
from services.prediction_watcher import PredictionWatcher
from services.cache_planner import CachePlanner
from services.cache_warmer import CacheWarmer
from services.self_critic import SelfCritic
from api.routes import router, set_dependencies

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("cache")


# ─── Global services ────────────────────────────────────────────────────────

watcher = PredictionWatcher()
planner = CachePlanner()
warmer = CacheWarmer()
critic = SelfCritic()
scheduler = AsyncIOScheduler()


def on_new_predictions(predictions):
    """Called by watcher when the AI writes new predictions."""
    plan = planner.build_plan(predictions)
    warmer.update_plan(plan)
    logger.info(f"📌 Plan updated: {sum(len(v) for v in plan.region_plans.values())} region plans")


watcher.register_callback(on_new_predictions)


# ─── Scheduler jobs ─────────────────────────────────────────────────────────

def poll_predictions():
    """Periodic job: check predictions file for changes."""
    watcher.check()


async def warmer_tick():
    """Periodic job: check if any plans are due to be warmed."""
    await warmer.tick()


async def critic_tick():
    """Periodic job: evaluate cache performance and write feedback if needed."""
    plan = warmer.current_plan
    if plan:
        critic.evaluate(plan)


# ─── FastAPI lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Cache Intelligence Module starting...")

    # Ensure predictions directory exists
    settings.predictions_file.parent.mkdir(parents=True, exist_ok=True)

    # Connect to Redis
    try:
        await warmer.connect()
    except Exception as exc:
        logger.warning(f"⚠️  Redis not available: {exc} — running in plan-only mode")

    # Register routes
    set_dependencies(warmer, watcher, planner, critic)

    # Start scheduler
    scheduler.add_job(
        poll_predictions,
        "interval",
        seconds=settings.watcher_poll_seconds,
        id="poll_predictions",
        replace_existing=True,
    )
    scheduler.add_job(
        warmer_tick,
        "interval",
        seconds=settings.warm_check_interval_seconds,
        id="warmer_tick",
        replace_existing=True,
    )
    scheduler.add_job(
        critic_tick,
        "interval",
        seconds=settings.critic_interval_seconds,
        id="critic_tick",
        replace_existing=True,
    )
    scheduler.start()

    # Initial check
    watcher.check()

    logger.info(
        f"✅ Ready — API on http://{settings.api_host}:{settings.api_port} | "
        f"Watching: {settings.predictions_file}"
    )

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await warmer.disconnect()
    logger.info("👋 Cache Intelligence Module stopped")


# ─── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cache Intelligence Module",
    description=(
        "Predictive cache pre-warming service. "
        "Receives AI predictions about upcoming high-demand events "
        "and pre-warms Redis cache entries to maximise hit rates."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
