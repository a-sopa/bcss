"""Canary analysis: is the new version behaving worse than the stable one?

Uses the router's per-version buckets (real traffic and health probes) since the canary started:
- error rate: canary vs stable, two-proportion z-test, plus an absolute floor;
- latency: canary p95 vs stable p95;
- the canary container crashing or being killed for memory.
"""

import math
from typing import Any

MIN_SAMPLES = 8
ERROR_FLOOR = 0.05  # never roll back for fewer than 5% failing requests
Z_THRESHOLD = 2.5
LATENCY_RATIO = 2.0
LATENCY_MARGIN_MS = 150


def window(metrics: dict | None, backend: str, since: float) -> dict[str, Any]:
    """Totals for one version since a time: requests, errors and latencies (real + probes)."""
    total = errors = 0
    latencies: list[float] = []
    if metrics:
        size = metrics.get("bucket_seconds", 5)
        for bucket in metrics.get("backends", {}).get(backend, []):
            if bucket["t"] + size < since:
                continue
            total += bucket["requests"] + bucket["probes"]
            errors += bucket["errors"] + bucket["probe_errors"]
            latencies += bucket["latency"] + bucket["probe_latency"]
    latencies.sort()
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    return {"requests": total, "errors": errors, "error_rate": errors / total if total else 0.0, "p95": p95}


def _z(errors_a: int, total_a: int, errors_b: int, total_b: int) -> float:
    pooled = (errors_a + errors_b) / max(1, total_a + total_b)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / max(1, total_a) + 1 / max(1, total_b)))
    if spread == 0:
        return math.inf if errors_a / max(1, total_a) > errors_b / max(1, total_b) else 0.0
    return (errors_a / total_a - errors_b / total_b) / spread


def verdict(metrics: dict | None, canary: str, stable: str, since: float, crashed: bool = False) -> dict[str, Any]:
    c, s = window(metrics, canary, since), window(metrics, stable, since)
    result: dict[str, Any] = {"canary": c, "stable": s, "anomalous": False, "reason": None, "enough_data": c["requests"] >= MIN_SAMPLES}
    if crashed:
        result.update(anomalous=True, reason="the canary container stopped (crash or out of memory)")
        return result
    if c["requests"] >= MIN_SAMPLES:
        z = _z(c["errors"], c["requests"], s["errors"], max(1, s["requests"]))
        result["z"] = round(z, 2) if math.isfinite(z) else None
        if c["error_rate"] >= max(ERROR_FLOOR, s["error_rate"] * 2) and z >= Z_THRESHOLD:
            result.update(anomalous=True, reason=(
                f"error rate {c['error_rate']:.0%} on the canary vs {s['error_rate']:.0%} on the stable version "
                f"({c['errors']}/{c['requests']} requests)"))
            return result
        if c["p95"] is not None and s["p95"] is not None and s["requests"] >= MIN_SAMPLES \
                and c["p95"] > s["p95"] * LATENCY_RATIO and c["p95"] - s["p95"] > LATENCY_MARGIN_MS:
            result.update(anomalous=True, reason=f"p95 latency {c['p95']:.0f} ms on the canary vs {s['p95']:.0f} ms on the stable version")
    return result
