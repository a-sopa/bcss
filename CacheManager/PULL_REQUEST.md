# Pull Request: feat(cache) — Predictive Cache Intelligence & Self-Critic Closed-Loop System

## 📌 Title Suggestion
`feat(cache): Predictive Cache Intelligence Engine with Self-Critic Feedback Loop`

---

## 🚀 Overview & Strategic Purpose
This PR introduces the **Cache Intelligence Module**, a proactive edge-caching and predictive pre-warming subsystem designed to eliminate the latency lag of traditional reactive CDNs and auto-scaling rules.

Instead of waiting for traffic surges to degrade user experience (reactive scaling), this module consumes predictive signals from the **AI Scraper / Gemini Analyzer** (popular real-world events, sports matches, concerts, commercial sales) with advance notice (`lead_time_minutes`), automatically pre-warming regional Redis instances with priority-scored entries and calibrated TTLs.

Furthermore, it implements a **Closed-Loop Self-Criticism Engine** that continually audits real cache performance and sends structured feedback back to the AI when actual hit rates fall short of expectations.

---

## ✨ Key Capabilities & Architectural Additions

### 1. 🧠 Predictive Pre-Warming & Prioritization
* **Multi-Factor Priority Scoring:**
  $$\text{Score} = \text{Confidence} \times \text{Traffic Multiplier} \times \text{Service Priority} \times \text{Time Urgency Factor}$$
* **Dynamic TTL & Memory Quotas:** Automatically allocates cache budget (`cache_size_mb`) per service and platform, protecting critical video streaming routes from cache thrashing.

### 2. 🔄 Closed-Loop Self-Criticism (`SelfCritic`)
* **Dynamic Thresholding:** Compares actual hit rate against AI confidence:
  $$\text{Expected Hit Rate} = \max(\text{AI Confidence} \times 0.75, \; 0.50)$$
* **Automated Feedback Emission:** If a region drops below the threshold after statistical significance ($\ge 50$ requests), writes `data/feedback.json` with root-cause gap analysis and targeted recommendations (e.g., doubling memory or advancing lead time).

### 3. 🛡️ Resilient Dual-Feed Ingestion
* **Native Gemini AI Feed Support:** Directly ingests `scraper-ai`'s output (`cache_manager_feed.json`), parsing regional AWS deployments, traffic multipliers, and `pre_warm_routes`.
* **Zero-Break Extensibility (`extra="allow"`):** Tolerates any new metadata injected by future AI scrapers without schema errors.
* **Flexible Date & Time Parsing:** Normalizes varied UTC ISO strings, UNIX timestamps, and regional offsets.

### 4. ⚡ High-Throughput Production Optimizations
* **Batch Redis Pipeline:** Eliminates network round-trips by bundling multi-key `HSET` and `EXPIRE` commands in a single async pipeline.
* **$O(1)$ Metric Tracking:** Instantaneous hit/miss registration via an in-memory direct key index map.
* **Non-Blocking Key Scans:** Replaced synchronous `KEYS` with async `scan_iter` for safe production flushing.
* **Incremental Reconciliation:** Updating predictions performs an in-place delta merge—never drops active `HOT` caches or wipes metric counters.

### 5. 🐳 Production Containerization
* Fully isolated with **Dockerfile** (Python 3.12 slim) and **Docker Compose** (`cache-intelligence` + `redis:alpine`) with persistent volume sharing.

---

## 📡 REST API Specifications

| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/health` | Service health status |
| `GET` | `/status` | Global operational summary and regional cache states |
| `GET` | `/predictions` | Active AI predictions and parameters loaded |
| `GET` | `/plan` | Complete cache warming plan with priority scores and TTLs |
| `GET` | `/metrics` | Aggregated cache hit/miss rates per region and service |
| `GET` | `/critique` | Latest Self-Critic performance report |
| `POST` | `/critique/run` | Force immediate self-critic evaluation (demo trigger) |
| `POST` | `/warm/{region}` | Trigger immediate manual pre-warming for a specific region |
| `DELETE` | `/cache/{region}` | Safely flush all cache keys within a region |
| `POST` | `/simulate/hit` | Simulate a cache hit for interactive demonstrations |
| `POST` | `/simulate/miss` | Simulate a cache miss for interactive demonstrations |

Interactive Swagger documentation available at `http://localhost:8001/docs`.

---

## 🧪 Validation & Test Results

All test suites pass with 100% success rate:

```text
🧪 Starting Extensibility & Robustness Tests...
✅ Test 1 Passed: Standard format loaded (3 events)
✅ Test 2 Passed: Gemini AI feed adapted (2 region events)
✅ Test 2b Passed: CachePlanner generated plan from Gemini AI feed
✅ Test 3 Passed: Extra fields safely preserved without schema rejection
✅ Test 4 Passed: O(1) hit/miss tracking verified on key 'cache:eu-south-1:feed-eu-south-0:sports:pt'

🎉 ALL EXTENSIBILITY AND EFFICIENCY TESTS PASSED!
```

```text
⚠️  Autocrítica [us-east-1] 'US Presidential Announcement': hit_rate=20.0% < esperado=50.0% → a pedir revisão ao AI
Avaliacao concluida:
  Regioes avaliadas: 2 | Regioes com falha: 1 | Overall passou: False | Feedback escrito para AI: True
  [OK] [eu-west-1] Benfica vs Porto - Primeira Liga (80.0% hit rate)
  [FALHOU] [us-east-1] US Presidential Announcement (20.0% hit rate) -> Feedback generated!
```

---

## 📦 How to Test & Review Locally

```bash
# 1. Start the complete stack (API + Redis)
cd cache
docker compose up -d --build

# 2. View live logs
docker compose logs -f cache-service

# 3. Trigger simulation demo
python demo.py
```
