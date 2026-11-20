"""Load generator: virtual users follow the learned Markov chain of pages, stage by stage.

Usage: python loadgen.py plan.json result.json   (standard library only)
"""

import http.client
import json
import random
import sys
import threading
import time
from urllib.parse import urlsplit


def pick(weights: dict[str, int]) -> str:
    items = list(weights.items())
    return random.choices([k for k, _ in items], weights=[w for _, w in items])[0]


def main(plan_file: str, result_file: str) -> None:
    plan = json.load(open(plan_file))
    target = urlsplit(plan["target"])
    regions = plan.get("regions") or {"frankfurt": 1}
    stages = []
    for stage in plan["stages"]:
        latencies: list[float] = []
        counts = {"requests": 0, "errors": 0}
        lock = threading.Lock()
        stop = time.time() + stage["seconds"]

        def user() -> None:
            connection = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=10)
            region = pick(regions)
            path = None
            while time.time() < stop:
                path = pick(plan["entry"]) if path is None else path
                started = time.perf_counter()
                failed = False
                try:
                    connection.request("GET", path, headers={"X-OwnCloud-Load-Test": "1", "X-OwnCloud-Region": region})
                    response = connection.getresponse()
                    response.read()
                    failed = response.status >= 500
                except (OSError, http.client.HTTPException):
                    failed = True
                    connection.close()
                    connection = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=10)
                with lock:
                    counts["requests"] += 1
                    counts["errors"] += failed
                    latencies.append((time.perf_counter() - started) * 1000)
                following = plan["transitions"].get(path)
                path = pick(following) if following and random.random() < 0.85 else None
                time.sleep(plan["think_time_s"] * random.uniform(0.5, 1.5))
            connection.close()

        threads = [threading.Thread(target=user, daemon=True) for _ in range(stage["users"])]
        started = time.time()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(stage["seconds"] + 15)
        elapsed = max(0.001, time.time() - started)
        latencies.sort()
        q = lambda p: round(latencies[min(len(latencies) - 1, int(len(latencies) * p))], 1) if latencies else None  # noqa: E731
        stages.append({
            "users": stage["users"], "seconds": round(elapsed, 1), "requests": counts["requests"],
            "rps": round(counts["requests"] / elapsed, 1),
            "error_rate": round(counts["errors"] / counts["requests"], 4) if counts["requests"] else 0.0,
            "p50_ms": q(0.5), "p95_ms": q(0.95), "p99_ms": q(0.99),
        })
        print(json.dumps(stages[-1]), flush=True)
    json.dump({"stages": stages}, open(result_file, "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
