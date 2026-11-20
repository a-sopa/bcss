"""Event forecast and preheat: the forecast service (scraper-ai + server-preheat + CacheManager) applied to apps.

The service predicts traffic peaks per region from real-world events (football, concerts, holidays…, analysed by
Gemini). Before a peak, every running app gets that region's edge cache filled by its router (preheat.json) and,
for large peaks, a higher CPU limit; afterwards everything returns to normal. The routers' real edge-cache hit
rates go back to the service, whose self-critic feeds them to the AI. See docs/integration.md.
"""

import hashlib
import json
import threading
import time
from datetime import datetime
from typing import Any

import httpx

from . import config


class Unavailable(Exception):
    """The forecast service could not be reached or answered with an error."""


def _call(method: str, path: str, timeout: float = 5, **kwargs: Any) -> Any:
    try:
        response = httpx.request(method, f"{config.FORECAST_URL}{path}", timeout=timeout, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise Unavailable(str(exc) or exc.__class__.__name__) from exc


def overview() -> dict[str, Any]:
    """Everything the console's forecast page shows."""
    result: dict[str, Any] = {"forecast": _call("GET", "/forecast")}
    for key, path in (("critique", "/critique"), ("metrics", "/metrics"), ("plan", "/plan")):
        try:
            result[key] = _call("GET", path)
        except Unavailable:
            result[key] = None
    return result


def run_now() -> dict[str, Any]:
    return _call("POST", "/forecast/run", timeout=120)


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class Preheater:
    """Keeps every app's routers and CPU limits in line with the service's preheat directive."""

    def __init__(self) -> None:
        self.directive: dict[str, Any] = {}
        self.fetched_at = 0.0
        self.error: str | None = None
        self.apps: dict[str, dict[str, Any]] = {}  # app_id → what was applied
        self.counters: dict[str, dict[str, dict[str, int]]] = {}  # app_id → region → last cumulative counters
        self.lock = threading.Lock()

    def refresh(self) -> dict[str, Any]:
        try:
            self.directive = _call("GET", "/preheat").get("regions") or {}
            self.error = None
        except Unavailable as exc:
            self.error = str(exc)
        self.fetched_at = time.time()
        return self.directive

    def active(self) -> dict[str, dict[str, Any]]:
        regions = {}
        for region, plan in self.directive.items():
            until = _timestamp(plan.get("until"))
            if plan.get("active") and until and until > time.time():
                regions[region] = {**plan, "until_ts": until}
        return regions

    def apply(self, runtime: Any, store: Any, record: dict[str, Any]) -> None:
        """Write the app's preheat.json and set its CPU limit for the regions that are preheating now."""
        app_id, version = record["id"], record["version"]
        active = self.active()
        content = {"regions": {region: {"until": plan["until_ts"], "event": plan.get("event"),
                                        "paths": plan.get("paths") or []}
                               for region, plan in active.items()}}
        factor = max([float(plan.get("cpu_factor") or 1) for plan in active.values()] or [1.0])
        factor = round(max(1.0, min(config.MAX_CPU_FACTOR, factor)), 2)
        digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        with self.lock:
            previous = self.apps.get(app_id, {})
        state = {**previous, "regions": active, "cpu_factor": factor, "version": version}
        if previous.get("digest") != digest or time.time() - previous.get("written_at", 0) > 60:
            if runtime.write_router_file(app_id, "preheat.json", content):
                state.update(digest=digest, written_at=time.time())
                started = sorted(set(active) - set(previous.get("regions") or {}))
                for region in started:
                    plan = active[region]
                    store.add_event(app_id, "forecast", "info", f"Preheating {region} for a predicted peak",
                                    f"{plan.get('event') or 'Event'}: ×{plan.get('multiplier', '?')} traffic expected; "
                                    f"edge cache warming until {datetime.fromtimestamp(plan['until_ts']):%H:%M}.")
        if previous.get("cpu_factor", 1.0) != factor or previous.get("version") != version:
            try:
                if runtime.set_cpus(app_id, version, config.APP_CPUS * factor):
                    if previous and previous.get("cpu_factor", 1.0) != factor:
                        store.add_event(app_id, "forecast", "info",
                                        f"CPU limit {'raised' if factor > previous.get('cpu_factor', 1.0) else 'restored'} "
                                        f"to {config.APP_CPUS * factor:g} CPUs",
                                        "Capacity requested by the server-preheat engine for the predicted peak."
                                        if factor > 1 else "The predicted peak is over.")
                else:
                    state["cpu_factor"] = previous.get("cpu_factor", 1.0)
            except Exception as exc:  # e.g. an older Docker engine: preheating the cache still works
                state.update(cpu_factor=previous.get("cpu_factor", 1.0), cpu_error=str(exc)[:200])
        with self.lock:
            self.apps[app_id] = state

    def observations(self, metrics_by_app: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
        """Deltas of the routers' edge-cache counters since the previous call, summed per region."""
        totals: dict[str, dict[str, int]] = {}
        for app_id, metrics in metrics_by_app.items():
            regions = (metrics.get("cache") or {}).get("regions") or {}
            last = self.counters.get(app_id, {})
            current: dict[str, dict[str, int]] = {}
            for region, data in regions.items():
                counters = {key: int(data.get(key, 0)) for key in ("hits", "misses", "prefetch_hits")}
                current[region] = counters
                before = last.get(region, {})
                # A restarted router starts again from zero: count everything it has seen since.
                delta = {key: value - before.get(key, 0) if value >= before.get(key, 0) else value
                         for key, value in counters.items()}
                if any(delta.values()):
                    total = totals.setdefault(region, {"hits": 0, "misses": 0, "prefetch_hits": 0, "requests": 0, "apps": 0})
                    for key, value in delta.items():
                        total[key] += value
                    total["requests"] += delta["hits"] + delta["misses"]
                    total["apps"] += 1
            self.counters[app_id] = current
        return totals

    def report(self, regions: dict[str, dict[str, int]], window: float) -> None:
        if regions:
            _call("POST", "/observations", json={"observed_at": datetime.utcnow().isoformat() + "Z",
                                                 "window_seconds": round(window), "regions": regions})

    def state(self, app_id: str) -> dict[str, Any]:
        with self.lock:
            applied = dict(self.apps.get(app_id) or {})
        return {
            "service": {"available": self.error is None and self.fetched_at > 0, "error": self.error,
                        "fetched_at": self.fetched_at or None},
            "regions": {region: {key: value for key, value in plan.items() if key != "engine"}
                        for region, plan in (applied.get("regions") or {}).items()},
            "cpu_factor": applied.get("cpu_factor", 1.0),
            "cpus": round(config.APP_CPUS * applied.get("cpu_factor", 1.0), 2),
            "cpu_error": applied.get("cpu_error"),
        }

    def forget(self, app_id: str) -> None:
        with self.lock:
            self.apps.pop(app_id, None)
            self.counters.pop(app_id, None)
