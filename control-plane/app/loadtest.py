"""Load tests generated from real traffic.

The router's request log (sanitised, real visitors only) gives: entry pages, a Markov chain of page
transitions, think time between requests and the observed peak rate. Virtual users replay that behaviour
in growing stages against the app's router (so caching and canaries count) until latency or errors break
the limits; the scenario can also be exported as a k6 script. Only GET requests are replayed.
"""

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ID_SEGMENT = re.compile(r"/(\d+|[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{16,})(?=/|$|\?)")
P95_LIMIT_MS = 1000
ERROR_LIMIT = 0.01
MAX_VIRTUAL_USERS = 200
GENERATOR = Path(__file__).parent / "router" / "loadgen.py"


def template(path: str) -> str:
    return ID_SEGMENT.sub("/{id}", path.split("?")[0])


def model(metrics: dict | None) -> dict[str, Any]:
    """Traffic model learned from real visitors."""
    log = [e for e in (metrics or {}).get("log", []) if not e.get("load") and e["method"] == "GET" and e["status"] < 500]
    if not log:
        return {"requests": 0, "paths": [], "entry": {}, "transitions": {}, "think_time_s": 1.0, "peak_rps": 0, "sessions": 0}
    by_client: dict[str, list[dict]] = defaultdict(list)
    for entry in sorted(log, key=lambda e: e["t"]):
        by_client[entry["client"]].append(entry)
    entry_pages, transitions, gaps = Counter(), defaultdict(Counter), []
    sessions = 0
    for visits in by_client.values():
        previous = None
        for visit in visits:
            if previous is None or visit["t"] - previous["t"] > 1800:
                entry_pages[visit["path"]] += 1
                sessions += 1
            else:
                transitions[previous["path"]][visit["path"]] += 1
                gaps.append(min(10.0, max(0.1, visit["t"] - previous["t"])))
            previous = visit
    per_second = Counter(int(e["t"]) for e in log)
    paths = Counter(e["path"] for e in log)
    templates = Counter(template(e["path"]) for e in log)
    return {
        "requests": len(log), "sessions": sessions,
        "paths": [{"path": p, "count": c} for p, c in paths.most_common(30)],
        "templates": [{"template": t, "count": c} for t, c in templates.most_common(15)],
        "entry": dict(entry_pages.most_common(20)),
        "transitions": {src: dict(dst.most_common(10)) for src, dst in transitions.items()},
        "think_time_s": round(statistics.median(gaps), 2) if gaps else 1.0,
        "peak_rps": max(per_second.values()),
        "regions": dict(Counter(e["region"] for e in log)),
    }


def plan(learned: dict[str, Any], max_users: int) -> dict[str, Any]:
    max_users = max(1, min(MAX_VIRTUAL_USERS, max_users))
    stages = sorted({max(1, max_users * f // 100) for f in (5, 10, 25, 50, 100)})
    return {"stages": [{"users": n, "seconds": 12} for n in stages], "think_time_s": max(0.05, learned["think_time_s"] / 4),
            "entry": learned["entry"] or {"/": 1}, "transitions": learned["transitions"], "regions": learned.get("regions", {})}


def evaluate(result: dict[str, Any]) -> dict[str, Any]:
    stages = result.get("stages", [])
    breaking = next((s for s in stages if (s["p95_ms"] or 0) > P95_LIMIT_MS or s["error_rate"] > ERROR_LIMIT), None)
    healthy = [s for s in stages if s is not breaking and ((s["p95_ms"] or 0) <= P95_LIMIT_MS and s["error_rate"] <= ERROR_LIMIT)]
    capacity = max((s["rps"] for s in healthy), default=0)
    if breaking:
        why = f"p95 {breaking['p95_ms']:.0f} ms" if (breaking["p95_ms"] or 0) > P95_LIMIT_MS else f"{breaking['error_rate']:.1%} errors"
        verdict = f"Handles about {capacity:.0f} req/s; at {breaking['users']} virtual users it breaks ({why})."
    else:
        verdict = f"No limit reached: {capacity:.0f} req/s at {stages[-1]['users'] if stages else 0} virtual users within limits."
    return {"capacity_rps": capacity, "breaking_stage": breaking, "verdict": verdict}


def run(runtime, app_id: str, test_plan: dict[str, Any]) -> dict[str, Any]:
    from .runtime import ROUTER_PORT

    target = f"http://{runtime.router_name(app_id)}:{ROUTER_PORT}"
    files = {"/loadgen.py": GENERATOR.read_bytes(), "/tmp/out/plan.json": json.dumps({**test_plan, "target": target}).encode()}
    duration = sum(s["seconds"] for s in test_plan["stages"]) + 60
    code, output, out = runtime.run_task(
        app_id, "python:3.12-slim", ["python", "-u", "/loadgen.py", "/tmp/out/plan.json", "/tmp/out/result.json"],
        role="loadtest", timeout=duration, files=files,
        limits={"mem_limit": "512m", "nano_cpus": int(1e9), "pids_limit": 512, "security_opt": ["no-new-privileges"], "cap_drop": ["ALL"]},
    )
    if "result.json" not in out:
        raise RuntimeError(f"The load generator failed: {output[-400:]}")
    result = json.loads(out["result.json"])
    return {**result, **evaluate(result)}


def k6_script(learned: dict[str, Any], base_url: str, max_users: int) -> str:
    """A k6 (https://k6.io, open source) script reproducing the learned traffic."""
    test_plan = plan(learned, max_users)
    stages = ",\n    ".join(f"{{ duration: '{s['seconds']}s', target: {s['users']} }}" for s in test_plan["stages"])
    return f"""// Generated by OwnCloud from real traffic ({learned['requests']} requests, {learned['sessions']} sessions).
// Run with: k6 run loadtest.js
import http from 'k6/http';
import {{ sleep }} from 'k6';

const BASE = {json.dumps(base_url)};
const ENTRY = {json.dumps(test_plan['entry'])};
const NEXT = {json.dumps(test_plan['transitions'])};

export const options = {{
  stages: [
    {stages}
  ],
  thresholds: {{ http_req_duration: ['p(95)<{P95_LIMIT_MS}'], http_req_failed: ['rate<{ERROR_LIMIT}'] }},
}};

function pick(weights) {{
  const entries = Object.entries(weights);
  let roll = Math.random() * entries.reduce((sum, [, w]) => sum + w, 0);
  for (const [value, weight] of entries) {{
    roll -= weight;
    if (roll <= 0) return value;
  }}
  return entries[0][0];
}}

export default function () {{
  let path = pick(ENTRY);
  for (let step = 0; step < 8 && path; step++) {{
    http.get(BASE + path, {{ headers: {{ 'X-OwnCloud-Load-Test': '1' }} }});
    sleep({test_plan['think_time_s']});
    path = NEXT[path] && Math.random() < 0.85 ? pick(NEXT[path]) : null;
  }}
}}
"""
