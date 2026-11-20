"""OwnCloud per-app router (data plane). Runs in its own container in front of an app's versions.

- Weighted traffic split between versions (stable / canary), from /config/routes.json.
- Metrics per version in 5-second buckets: requests, 5xx/502 errors, latency — real traffic and health probes.
- Request log (sanitised) and a Markov model of navigation, used for prefetching and load-test generation.
- Edge cache per region (logical edge locations; one router hosts them all): only anonymous GET/HEAD
  responses that are explicitly cacheable, plus static assets. Predictive prefetch fills a region's cache
  with the pages its visitors are likely to request next, and re-warms popular pages before they expire.
- Writes everything to /tmp/metrics.json every second; the control plane reads it through the Docker API.
Standard library only.
"""

import hashlib
import http.client
import json
import os
import random
import re
import threading
import time
from collections import Counter, OrderedDict, defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

CONFIG = os.environ.get("ROUTER_CONFIG", "/config/routes.json")
METRICS = os.environ.get("ROUTER_METRICS", "/tmp/metrics.json")
BUCKET_SECONDS = 5
KEEP_BUCKETS = 180  # 15 minutes
MAX_BODY = 50 * 1024 * 1024
CACHE_BYTES = 64 * 1024 * 1024
CACHE_ENTRY_BYTES = 2 * 1024 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length"}
SENSITIVE = re.compile(r"(?i)(token|key|secret|pass|session|auth|code|sig|email|jwt)")
STATIC = re.compile(r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|map)$", re.I)
REGION_HEADER = "x-owncloud-region"
REGION_PATTERN = re.compile(r"^[a-z][a-z-]{1,30}$")
LANGUAGE_REGIONS = {"pt": "lisbon", "es": "madrid", "fr": "paris", "de": "frankfurt", "it": "milan", "nl": "amsterdam",
                    "pl": "warsaw", "en": "dublin"}
LOAD_TEST_HEADER = "x-owncloud-load-test"


def now() -> float:
    return time.time()


def sanitise(path: str) -> str:
    """Path with sensitive query values removed (never logged or modelled)."""
    parts = urlsplit(path)
    query = [(k, "redacted" if SENSITIVE.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return parts.path + (f"?{urlencode(query)}" if query else "")


class Config:
    def __init__(self) -> None:
        self.mtime = 0.0
        self.data = {"backends": [], "cache": True, "probe_paths": ["/"], "probe_interval": 2}
        self.lock = threading.Lock()

    def current(self) -> dict:
        try:
            mtime = os.stat(CONFIG).st_mtime
            if mtime != self.mtime:
                with open(CONFIG) as handle:
                    data = json.load(handle)
                with self.lock:
                    self.data, self.mtime = {**self.data, **data}, mtime
        except (OSError, ValueError):
            pass
        return self.data

    def pick(self) -> dict | None:
        backends = [b for b in self.current()["backends"] if b.get("weight", 0) > 0]
        if not backends:
            return None
        return random.choices(backends, weights=[b["weight"] for b in backends])[0]

    def stable(self) -> dict | None:
        backends = self.current()["backends"]
        return next((b for b in backends if b.get("role") == "stable"), backends[0] if backends else None)


class Stats:
    def __init__(self) -> None:
        self.buckets: dict[str, OrderedDict[int, dict]] = defaultdict(OrderedDict)
        self.lock = threading.Lock()

    def record(self, backend: str, status: int, latency_ms: float, kind: str = "real") -> None:
        key = int(now() // BUCKET_SECONDS) * BUCKET_SECONDS
        with self.lock:
            buckets = self.buckets[backend]
            bucket = buckets.get(key)
            if bucket is None:
                bucket = buckets[key] = {"t": key, "requests": 0, "errors": 0, "latency": [], "probes": 0,
                                         "probe_errors": 0, "probe_latency": [], "load": 0}
                while len(buckets) > KEEP_BUCKETS:
                    buckets.popitem(last=False)
            error = status >= 500
            if kind == "probe":
                bucket["probes"] += 1
                bucket["probe_errors"] += error
                if len(bucket["probe_latency"]) < 200:
                    bucket["probe_latency"].append(round(latency_ms, 1))
            else:
                bucket["requests"] += 1
                bucket["errors"] += error
                bucket["load"] += kind == "load"
                if len(bucket["latency"]) < 500:
                    bucket["latency"].append(round(latency_ms, 1))

    def snapshot(self) -> dict:
        with self.lock:
            return {name: list(buckets.values()) for name, buckets in self.buckets.items()}


class Traffic:
    """Sanitised request log plus a per-region Markov model of navigation."""

    def __init__(self) -> None:
        self.log: deque[dict] = deque(maxlen=5000)
        self.transitions: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        self.last: dict[str, tuple[str, float]] = {}
        self.lock = threading.Lock()

    def record(self, entry: dict, learn: bool) -> list[str]:
        """Store a request; returns the paths this visitor is likely to request next (for prefetching).
        Synthetic traffic (load tests) is counted in the metrics but never logged, so it cannot push real
        visitors out of the log the traffic model is learned from."""
        if not learn:
            return []
        with self.lock:
            self.log.append(entry)
            if entry["method"] != "GET" or entry["status"] >= 400:
                return []
            client, path, region = entry["client"], entry["path"], entry["region"]
            previous = self.last.get(client)
            if previous and entry["t"] - previous[1] < 1800 and previous[0] != path:
                self.transitions[region][previous[0]][path] += 1
            self.last[client] = (path, entry["t"])
            if len(self.last) > 20000:
                self.last.clear()
            following = self.transitions[region].get(path, Counter())
            total = sum(following.values())
            return [nxt for nxt, count in following.most_common(3) if count >= 3 and count / total >= 0.25]

    def popular(self, region: str, since: float, limit: int = 10) -> list[str]:
        with self.lock:
            counts = Counter(e["path"] for e in self.log if e["region"] == region and e["t"] >= since and e["method"] == "GET")
        return [path for path, _ in counts.most_common(limit)]

    def snapshot(self) -> dict:
        with self.lock:
            transitions = [
                {"region": region, "from": src, "to": dst, "count": count}
                for region, sources in self.transitions.items()
                for src, targets in sources.items()
                for dst, count in targets.items()
            ]
            return {"log": list(self.log)[-2000:], "transitions": sorted(transitions, key=lambda t: -t["count"])[:200]}


class EdgeCache:
    def __init__(self) -> None:
        self.regions: dict[str, OrderedDict[str, dict]] = defaultdict(OrderedDict)
        self.bytes = 0
        self.stats: dict[str, Counter] = defaultdict(Counter)
        self.lock = threading.Lock()

    @staticmethod
    def ttl(path: str, status: int, headers: dict[str, str]) -> int:
        if status != 200 or "set-cookie" in headers:
            return 0
        control = headers.get("cache-control", "").lower()
        if any(word in control for word in ("private", "no-store", "no-cache")):
            return 0
        match = re.search(r"s-maxage=(\d+)", control) or re.search(r"max-age=(\d+)", control)
        if match:
            return min(int(match.group(1)), 3600)
        return 60 if STATIC.search(urlsplit(path).path) else 0

    def get(self, region: str, path: str) -> dict | None:
        with self.lock:
            entry = self.regions[region].get(path)
            if entry is None or entry["expires"] < now():
                self.stats[region]["misses"] += 1
                return None
            self.regions[region].move_to_end(path)
            self.stats[region]["hits"] += 1
            self.stats[region]["bytes_saved"] += len(entry["body"])
            if entry["prefetched"] and not entry["used"]:
                self.stats[region]["prefetch_hits"] += 1
            entry["used"] = True
            return entry

    def has(self, region: str, path: str, margin: float = 0) -> bool:
        with self.lock:
            entry = self.regions[region].get(path)
            return entry is not None and entry["expires"] > now() + margin

    def put(self, region: str, path: str, status: int, headers: dict[str, str], body: bytes, ttl: int, prefetched: bool) -> None:
        if ttl <= 0 or len(body) > CACHE_ENTRY_BYTES:
            return
        with self.lock:
            entries = self.regions[region]
            old = entries.pop(path, None)
            if old:
                self.bytes -= len(old["body"])
            entries[path] = {"expires": now() + ttl, "status": status, "headers": headers, "body": body,
                             "prefetched": prefetched, "used": False}
            self.bytes += len(body)
            self.stats[region]["prefetched" if prefetched else "stored"] += 1
            while self.bytes > CACHE_BYTES:
                biggest = max(self.regions, key=lambda r: len(self.regions[r]))
                _, evicted = self.regions[biggest].popitem(last=False)
                self.bytes -= len(evicted["body"])

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "bytes": self.bytes,
                "regions": {
                    region: {"entries": len(self.regions[region]), **dict(self.stats[region])}
                    for region in set(self.regions) | set(self.stats)
                },
            }


config, stats, traffic, cache = Config(), Stats(), Traffic(), EdgeCache()
prefetch_queue: deque[tuple[str, str]] = deque(maxlen=200)


def region_of(headers) -> str:
    explicit = (headers.get(REGION_HEADER) or "").strip().lower()
    if REGION_PATTERN.match(explicit):
        return explicit
    language = (headers.get("accept-language") or "").split(",")[0].strip().lower()[:2]
    return LANGUAGE_REGIONS.get(language, "frankfurt")


def forward(backend: dict, method: str, path: str, headers: dict[str, str], body: bytes | None, timeout: float = 30):
    """(status, headers, body) from a backend; 502 when it cannot be reached."""
    connection = http.client.HTTPConnection(backend["host"], backend["port"], timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            return 502, {"content-type": "text/plain"}, b"Response too large"
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data
    except (OSError, http.client.HTTPException):
        return 502, {"content-type": "text/plain"}, b"Bad gateway: the app did not respond"
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OwnCloud"
    sys_version = ""

    def log_message(self, *args) -> None:  # metrics replace access logs
        pass

    def _reply(self, status: int, headers: dict[str, str], body: bytes, extra: dict[str, str]) -> None:
        self.send_response(status)
        for key, value in headers.items():
            if key not in HOP_BY_HOP:
                self.send_header(key, value)
        for key, value in extra.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self) -> None:
        started = time.perf_counter()
        if self.path.startswith("/__owncloud"):
            return self._reply(404, {"content-type": "text/plain"}, b"Not found", {})
        if self.headers.get("transfer-encoding"):
            return self._reply(411, {"content-type": "text/plain"}, b"Length required", {})
        length = int(self.headers.get("content-length") or 0)
        if length > MAX_BODY:
            return self._reply(413, {"content-type": "text/plain"}, b"Too large", {})
        body = self.rfile.read(length) if length else None

        region = region_of(self.headers)
        load_test = self.headers.get(LOAD_TEST_HEADER) == "1"
        anonymous = not self.headers.get("authorization") and not self.headers.get("cookie")
        cacheable = self.command in ("GET", "HEAD") and anonymous and config.current().get("cache", True)
        client = hashlib.sha256(f"{self.client_address[0]}|{self.headers.get('user-agent', '')}".encode()).hexdigest()[:12]

        entry = cache.get(region, self.path) if cacheable else None
        if entry:
            status, headers, data, backend_name = entry["status"], entry["headers"], entry["body"], "edge"
            extra = {"X-OwnCloud-Cache": "PREFETCHED" if entry["prefetched"] else "HIT", "X-OwnCloud-Edge": region}
        else:
            backend = config.pick()
            if backend is None:
                return self._reply(503, {"content-type": "text/plain"}, b"No version is running", {})
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            headers["Host"] = self.headers.get("host", "app")
            headers["X-Forwarded-For"] = self.client_address[0]
            headers["X-Forwarded-Proto"] = "http"
            status, headers, data = forward(backend, self.command, self.path, headers, body)
            backend_name = backend["name"]
            latency = (time.perf_counter() - started) * 1000
            stats.record(backend_name, status, latency, "load" if load_test else "real")
            extra = {"X-OwnCloud-Version": backend_name, "X-OwnCloud-Edge": region}
            if cacheable:
                ttl = cache.ttl(self.path, status, headers)
                if ttl:
                    cache.put(region, self.path, status, headers, data, ttl, prefetched=False)
                extra["X-OwnCloud-Cache"] = "MISS" if ttl else "BYPASS"

        latency = (time.perf_counter() - started) * 1000
        self._reply(status, headers, data, extra)
        predicted = traffic.record({
            "t": round(now(), 3), "client": client, "method": self.command, "path": sanitise(self.path),
            "status": status, "ms": round(latency, 1), "backend": backend_name, "region": region,
            "cache": extra.get("X-OwnCloud-Cache", "BYPASS"), "load": load_test,
        }, learn=not load_test)
        if cacheable:
            for path in predicted:
                if not cache.has(region, path):
                    prefetch_queue.append((region, path))

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle


def prefetcher() -> None:
    """Fill edge caches ahead of demand: predicted next pages and popular pages about to expire."""
    last_warm = 0.0
    while True:
        try:
            if time.time() - last_warm > 10:
                last_warm = time.time()
                regions = {e["region"] for e in traffic.snapshot()["log"][-500:]}
                for region in regions:
                    for path in traffic.popular(region, since=now() - 300, limit=8):
                        if not cache.has(region, path, margin=15) and len(prefetch_queue) < 150:
                            prefetch_queue.append((region, path))
            if not prefetch_queue:
                time.sleep(0.05)
                continue
            region, path = prefetch_queue.popleft()
            backend = config.stable()
            if backend is None or cache.has(region, path) or not config.current().get("cache", True):
                continue
            status, headers, data = forward(backend, "GET", path, {"Host": "app", "X-OwnCloud-Prefetch": "1"}, None, 10)
            ttl = cache.ttl(path, status, headers)
            if ttl:
                cache.put(region, path, status, headers, data, ttl, prefetched=True)
            time.sleep(0.05)  # at most ~20 prefetches per second
        except Exception:
            time.sleep(1)


def prober() -> None:
    """Health probes: every version gets the same few GET requests, so even a 5% canary is measured quickly."""
    while True:
        current = config.current()
        paths = list(dict.fromkeys(current.get("probe_paths") or ["/"]))[:5]
        for backend in current["backends"]:
            for path in paths:
                started = time.perf_counter()
                status, _, _ = forward(backend, "GET", path, {"Host": "app", "X-OwnCloud-Probe": "1"}, None, 10)
                stats.record(backend["name"], status, (time.perf_counter() - started) * 1000, "probe")
        time.sleep(max(1, float(current.get("probe_interval", 2))))


def writer() -> None:
    while True:
        snapshot = {"time": now(), "bucket_seconds": BUCKET_SECONDS, "routes": config.current(), "backends": stats.snapshot(),
                    "cache": cache.snapshot(), **traffic.snapshot()}
        temporary = METRICS + ".tmp"
        with open(temporary, "w") as handle:
            json.dump(snapshot, handle)
        os.replace(temporary, METRICS)
        time.sleep(1)


if __name__ == "__main__":
    for worker in (prefetcher, prober, writer):
        threading.Thread(target=worker, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler)
    server.daemon_threads = True
    server.serve_forever()
