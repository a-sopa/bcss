"""End-to-end test of OwnCloud's AI features against the running stack (docker compose up).

    control-plane/.venv/bin/python scripts/test-ai-features.py

With a temporary account and the examples/apps/smart-shop app it checks: smart CI (only impacted tests),
canary promotion, automatic rollback with root-cause analysis, edge caching and prefetching, generated
load tests (and the k6 export), the managed database with autonomous indexing, and manual rollback.
Everything it creates is deleted at the end. Takes several minutes (image builds and canary windows).
"""

import random
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "security-tests"))
from conftest import browser, cli  # noqa: E402

APP = ROOT / "examples" / "apps" / "smart-shop"
LANGUAGES = ["pt-PT", "de-DE", "fr-FR", "pt-PT", "es-ES"]
results: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append(f"{'✓' if condition else '✗'} {name}" + (f" — {detail}" if detail else ""))
    print(results[-1], flush=True)
    if not condition:
        raise AssertionError(name)


def wait(client: httpx.Client, app_id: str, done, timeout: float = 400, label: str = "") -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app = client.get(f"/api/apps/{app_id}").json()
        if done(app):
            return app
        time.sleep(3)
    raise AssertionError(f"timed out waiting for {label}: {app.get('status')} {app.get('detail')}")


class Visitors:
    """Real-looking visitors browsing the shop through its public address (the router)."""

    def __init__(self, url: str):
        self.url, self.stop, self.count = url, threading.Event(), 0

    def browse(self, visitors: int = 1, think: float = 0.05) -> None:
        for n in range(visitors):
            headers = {"Accept-Language": random.choice(LANGUAGES), "User-Agent": f"visitor-{random.randint(1, 10**9)}"}
            with httpx.Client(base_url=self.url, timeout=10, headers=headers) as session:
                for path in ["/", "/static/style.css", "/products", f"/products/{random.randint(1, 5)}", "/products", "/products/1"]:
                    try:
                        session.get(path)
                        self.count += 1
                    except httpx.HTTPError:
                        pass
                    time.sleep(think)

    def background(self) -> threading.Thread:
        def loop():
            while not self.stop.is_set():
                self.browse()
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread


def latest(client: httpx.Client, app_id: str) -> dict:
    return client.get(f"/api/apps/{app_id}/deployments").json()[0]


def main() -> int:
    user = f"ai-test-{random.randint(1000, 9999)}"
    client = browser(user, cli("create", user))
    app_id = None
    try:
        files = [("files", (f"smart-shop/{p.relative_to(APP).as_posix()}", p.read_bytes()))
                 for p in sorted(APP.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
        app_id = client.post("/api/apps", data={"name": "smart-shop"}, files=files).json()["id"]

        # 1. First deployment: full suite, then the app runs behind its router.
        app = wait(client, app_id, lambda a: a["status"] in ("running", "failed"), label="first deploy")
        check("first deployment runs", app["status"] == "running", app.get("detail") or "")
        first = latest(client, app_id)
        check("first pipeline runs the full suite", first["pipeline"]["mode"] == "full" and first["pipeline"]["status"] == "passed",
              f"{first['pipeline']['passed']} tests passed in {first['pipeline']['duration']} s")
        url = app["url"]
        check("app is served by its router on 127.0.0.1", url.startswith("http://127.0.0.1:"), url)

        # 2. Edge cache and predictive prefetch, learned from visitors.
        visitors = Visitors(url)
        visitors.browse(40)  # visitors teach the router how people navigate, per region
        time.sleep(35)  # cached pages expire (max-age=30), so the next visitors' pages must be prefetched to be hits
        visitors.browse(12, think=0.3)  # realistic think time between pages
        time.sleep(2)
        traffic = client.get(f"/api/apps/{app_id}/traffic").json()
        regions = traffic["cache"]["regions"]
        hits = sum(r.get("hits", 0) for r in regions.values())
        prefetched = sum(r.get("prefetched", 0) for r in regions.values())
        prefetch_hits = sum(r.get("prefetch_hits", 0) for r in regions.values())
        check("edge cache serves repeat requests per region", hits > 20 and len(regions) >= 3,
              f"{hits} hits across {sorted(regions)}; {traffic['cache']['served_from_edge']} of {traffic['cache']['requests']} requests from the edge")
        check("prefetching fills caches before visitors ask", prefetched > 0 and prefetch_hits > 0,
              f"{prefetched} pages prefetched, {prefetch_hits} later requested")
        check("navigation is learned", len(traffic["predictions"]) > 0,
              f"e.g. {traffic['predictions'][0]['from']} → {traffic['predictions'][0]['to']}")

        # 3. Smart CI + canary promotion: a pricing change runs only the pricing tests.
        source = client.get(f"/api/apps/{app_id}/file", params={"path": "pricing.py"}).json()["content"]
        client.put(f"/api/apps/{app_id}/file", params={"path": "pricing.py"},
                   json={"content": source.replace('"coffee": 0.0', '"coffee": 0.05')})
        background = visitors.background()
        client.post(f"/api/apps/{app_id}/redeploy")
        wait(client, app_id, lambda a: a["status"] == "canary", label="canary start", timeout=300)
        check("new version starts as a canary", True, f"{latest(client, app_id)['pipeline']['reason']}")
        app = wait(client, app_id, lambda a: a["status"] in ("running", "failed") and not a["canary_version"], label="promotion")
        second = latest(client, app_id)
        check("only the impacted tests ran", second["pipeline"]["tests"] == ["tests/test_pricing.py"],
              f"{len(second['pipeline']['tests'])} of {len(second['pipeline']['all_tests'])} test files; "
              f"~{second['pipeline']['estimated_saving']} s saved")
        check("healthy canary is promoted", second["status"] == "promoted" and app["version"] == second["version"],
              f"canary error rate {second['canary']['canary']['error_rate']:.0%} over {second['canary']['canary']['requests']} requests")

        # 4. A bad change: tests still pass, the canary catches it, rolls back and explains why.
        source = client.get(f"/api/apps/{app_id}/file", params={"path": "catalog.py"}).json()["content"]
        client.put(f"/api/apps/{app_id}/file", params={"path": "catalog.py"},
                   json={"content": source.replace(' if count else 0.0', '')})
        client.post(f"/api/apps/{app_id}/redeploy")
        app = wait(client, app_id, lambda a: a["status"] == "running" and not a["canary_version"] and latest(client, app_id)["status"] != "running",
                   label="rollback")
        third = latest(client, app_id)
        check("bad canary is rolled back automatically", third["status"] == "rolled_back" and app["version"] == second["version"],
              third["canary"]["reason"] if third["canary"] else "")
        incident = client.get(f"/api/apps/{app_id}/incidents").json()[0]
        report = incident["report"]
        check("root cause names the changed line", report["culprit"]["file"] == "catalog.py" and report["culprit"]["changed_in_this_version"],
              report["summary"])
        check("root cause suggests a fix", "divisor" in report["hint"] and bool(report["suggested_fix"]["revert"]), report["hint"])
        # The rollback protects production; the developer then applies the suggested fix to the source.
        client.put(f"/api/apps/{app_id}/file", params={"path": "catalog.py"}, json={"content": source})
        visitors.stop.set()
        background.join(15)

        # 5. Load test generated from the real traffic.
        model = client.get(f"/api/apps/{app_id}/loadtest/model").json()
        check("traffic model learned from visitors", model["requests"] > 50 and model["transitions"],
              f"{model['requests']} requests, {model['sessions']} sessions, think time {model['think_time_s']} s")
        client.post(f"/api/apps/{app_id}/loadtests", json={"max_users": 20})
        deadline = time.time() + 240
        while time.time() < deadline:
            test = client.get(f"/api/apps/{app_id}/loadtests").json()[0]
            if test["status"] != "running":
                break
            time.sleep(5)
        check("load test runs in stages", test["status"] == "finished" and len(test["result"]["stages"]) >= 3,
              test["result"].get("verdict", test["result"].get("error", "")))
        script = client.get(f"/api/apps/{app_id}/loadtest/k6").text
        check("k6 script is exported", "export default function" in script and "/products" in script)

        # 6. Managed database: slow query → index created automatically.
        client.post(f"/api/apps/{app_id}/database")
        app = wait(client, app_id, lambda a: a["status"] == "running" and latest(client, app_id)["status"] in ("promoted", "deployed", "rolled_back", "failed"),
                   label="redeploy with database", timeout=500)
        check("database attached and app redeployed", latest(client, app_id)["status"] in ("promoted", "deployed"), app.get("detail") or "")
        with httpx.Client(base_url=app["url"], timeout=30) as shop:
            for n in range(40):
                shop.get("/orders", params={"email": f"customer{n * 37 % 20000}@example.eu"})
            for page in range(5):
                shop.get("/orders/recent", params={"page": 400 + page})
        actions = client.post(f"/api/apps/{app_id}/database/optimize").json()["actions"]
        status = client.get(f"/api/apps/{app_id}/database").json()
        created = [a for a in status["actions"] if a["kind"] == "index_created"]
        check("slow query gets an index automatically", any("customer_email" in a["statement"] for a in created),
              ", ".join(f"{a['detail']['index']}: cost {a['detail']['cost_before']:.0f} → {a['detail']['cost_after']:.0f}" for a in created))
        suggestions = [a["detail"]["rule"] for a in status["actions"] if a["kind"] == "suggestion"]
        check("query rewrites are suggested", "offset" in suggestions or "select-star" in suggestions, ", ".join(sorted(set(suggestions))))
        with httpx.Client(base_url=app["url"], timeout=30) as shop:
            for n in range(10):
                shop.get("/orders", params={"email": f"customer{n}@example.eu"})
        after = client.get(f"/api/apps/{app_id}/database").json()
        timing = next((a["detail"] for a in after["actions"] if a["kind"] == "index_created"), {})
        check("query is faster after the index", timing.get("mean_ms_now") is not None and timing["mean_ms_now"] < timing["mean_ms_before"],
              f"{timing.get('mean_ms_before')} ms → {timing.get('mean_ms_now')} ms")

        # 7. Manual rollback to the previous version.
        before = client.get(f"/api/apps/{app_id}").json()["version"]
        rolled = client.post(f"/api/apps/{app_id}/rollback")
        check("manual rollback", rolled.status_code == 200 and rolled.json()["version"] < before,
              f"v{before} → v{rolled.json().get('version')}")
    finally:
        if app_id:
            client.delete(f"/api/apps/{app_id}")
        client.close()
        cli("delete", user, check=False)
    print(f"\n{sum(r.startswith('✓') for r in results)} of {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f"\nFAILED: {error}")
        sys.exit(1)
