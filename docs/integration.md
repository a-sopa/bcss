# OwnCloud integration: forecast and threat services

OwnCloud's control plane (`control-plane/`) applies the team's AI modules to every hosted app. Two internal
services carry the colleagues' work; the control plane is their only client and the console (signed in) is the
only way users see their data. Neither service is published on the host, apart from the honeypot's network
decoys.

```
                    ┌──────────────── forecast (CacheManager + scraper-ai + server-preheat) ──────────────┐
 events (football,  │ collect_all_events → Gemini / heuristics → per-region multiplier → preheat plan     │
 PredictHQ, Ticket- │ → cache plan (Redis) → self-critic (real hit rates from routers) → feedback → AI    │
 master, manual,    └───────────────▲──────────────────────────────┬──────────────────────────────────────┘
 holidays)                          │ POST /observations           │ GET /preheat, /forecast, /plan, /critique
                                    │ (real edge-cache hits)       ▼
                              ┌─────┴──────────── control plane (autopilot, every 10–60 s) ────────────────┐
                              │ preheat.json + CPU boost per app · security.json (decoys, blocks, canaries)│
                              └─────▲──────────────────────────────┬──────────────────────────────────────┘
                                    │ router metrics: threat events │ POST /api/ingest, GET /api/sessions …
                                    │ (decoy hits, canary use)      ▼
 per-app routers (data plane) ──────┘          threats (cloud_honeypot_ai): sessions, MITRE, bot classifier,
                                                vault, canary keys, honey dumps, defense rules, SSH/Telnet decoys
```

OwnCloud regions (logical edge locations of every router): `lisbon, madrid, paris, frankfurt, milan, amsterdam,
warsaw, dublin`.

Country → region (ISO 3166-1 alpha-2; anything else → `frankfurt`):

| Region | Countries |
| --- | --- |
| lisbon | PT |
| madrid | ES, AD |
| paris | FR, BE, LU, MC, CH |
| frankfurt | DE, AT, CZ, SK, HU, SI, HR, RS, BA, ME, MK, AL, LI |
| milan | IT, MT, SM, VA, GR, CY, BG, RO |
| amsterdam | NL, DK, SE, NO, FI, IS, EE, LV, LT |
| warsaw | PL, UA, BY, MD |
| dublin | IE, GB |

## Forecast service (`forecast`, internal port 8001)

Built from `CacheManager/Dockerfile` with the repository root as context (it also copies `scraper-ai/` and
`server-preheat/`). Data in `/data` (volume). Redis is internal. Environment: `GEMINI_API_KEY`, `GEMINI_MODEL`,
`FOOTBALL_API_KEY`, `PREDICTHQ_TOKEN`, `TICKETMASTER_API_KEY` (each optional: a source without a key is
disabled and reported as such), `FORECAST_INTERVAL_SECONDS` (default 1800), `CACHE_REDIS_HOST`, `CACHE_DATA_DIR`.

All responses are JSON. Times are ISO 8601 UTC strings.

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | `{status, timestamp}` |
| GET | `/forecast` | see below |
| POST | `/forecast/run` | runs collection + analysis now (≤ 60 s), then the same body as `GET /forecast` |
| GET | `/preheat` | see below: the directive the control plane applies to every app |
| POST | `/observations` | body below; returns `{accepted: true, regions: [..]}` |
| GET | `/plan`, `/metrics`, `/status`, `/predictions` | the CacheManager responses, keyed by OwnCloud region |
| GET | `/critique` / POST `/critique/run` | self-critic report / run now |

`GET /forecast`:

```json
{
  "generated_at": "…", "next_run_at": "…", "running": false,
  "ai": {"gemini_active": true, "model": "gemini-2.5-flash", "analyzed_by": {"gemini": 12, "local_heuristic": 3},
         "last_error": null},
  "sources": {"football": {"enabled": false, "events": 0, "error": null}, "predicthq": {…}, "ticketmaster": {…},
              "manual": {…}, "holidays": {…}},
  "feedback": {"found": true, "failed_regions": ["lisbon"]},
  "regions": {"lisbon": {"multiplier_now": 1.0, "peak_multiplier_24h": 2.4, "status": "normal|preheat|peak",
                         "target_capacity": 31, "next_event": "…description…", "next_event_start": "…"}},
  "events": [{"id": "…", "region": "lisbon", "country": "PT", "description": "…", "category": "sports",
              "source": "football", "start": "…", "end": "…", "warm_at": "…", "multiplier": 2.4,
              "confidence": 0.8, "analyzed_by": "gemini", "reasoning": "…", "cache_strategy": "…",
              "ttl_seconds": 300}]
}
```

`events` holds the next 7 days (sorted by start, at most 200). `warm_at = start − lead time` (default 20 min,
longer for larger multipliers).

`GET /preheat`:

```json
{
  "generated_at": "…",
  "regions": {
    "lisbon": {"active": true, "event_id": "…", "event": "…", "multiplier": 2.4, "warm_at": "…", "until": "…",
               "cpu_factor": 2.0, "ttl_seconds": 300, "target_capacity": 31, "engine": {…ServerPreheatEngine result…}}
  }
}
```

A region is `active` from `warm_at` until the end of its event (the strongest event if several overlap). Regions
with nothing active are omitted. `cpu_factor` ∈ [1, 4] is the capacity the server-preheat engine asks for
relative to normal (from its target vs baseline capacity).

`POST /observations` (the real edge-cache counters of all routers, as deltas since the previous post):

```json
{"observed_at": "…", "window_seconds": 60,
 "regions": {"lisbon": {"hits": 120, "misses": 30, "prefetch_hits": 40, "requests": 150, "apps": 3}}}
```

The self-critic compares these real hit rates with each active plan's expected hit rate (instead of the
`/simulate/*` counters, which stay for tests) and writes feedback for the AI as before.

## Threat service (`threats`, internal API port 8888)

Built from `cloud_honeypot_ai/Dockerfile`. Data (sessions, vault and its keys, canary registry, firewall rules) in
`/data` (volume): keys are generated on first start and never committed. Environment: `HONEYPOT_DATA_DIR`,
`HONEYPOT_HOSTNAME`, `HONEYPOT_SSH_PORT`, `HONEYPOT_TELNET_PORT`, `HONEYPOT_HTTP_PORT`, `HONEYPOT_API_PORT`,
`HONEYPOT_CALLBACK_URL` (where canary callbacks point; default the HTTP decoy), `GEOIP_ONLINE` (default false;
synthetic locations are flagged `"geo": {"source": "synthetic"}`).

| Method | Path | Body / response |
| --- | --- | --- |
| GET | `/api/status` | `{status, version, sessions, decoys: {ssh, telnet, http}}` |
| POST | `/api/ingest` | events from OwnCloud routers (below) → `{sessions: [verdict]}` |
| GET | `/api/sessions?app_id=&source=&limit=` | sessions, newest first (`source`: `owncloud` or `decoy`) |
| GET | `/api/sessions/{id}` | one session with its threat report |
| GET | `/api/summary?app_id=` | `{sessions, attackers, by_level, top_techniques[{id,name,count}], canary_triggers, vault: {blocks, integrity_valid}}` |
| PUT | `/api/canary/{app_id}` | creates (or returns the existing) canary bundle for an app |
| POST | `/api/leaks/verify` | `{text}` → `{leak: {app_id, session_id, …} \| null}` |
| GET | `/api/honeydump/{app_id}` | `{sql}`: watermarked fake customer dump for that app's decoys |
| POST | `/api/defense` | `{ips: [..]}` → `{metrics, rules: {iptables, aws_nacl_cli, aws_sg_cli, cloudflare_waf, terraform}}` (pure) |
| GET | `/api/vault` | `{integrity_valid, errors, blocks: [{index, session_id, sealed_at, hash}]}` |
| GET | `/api/vault/{session_id}` | the decrypted sealed session |
| GET | `/api/deception`, `/api/crypto` | as before |
| POST | `/api/simulate` | as before (only reachable through the control plane, admins only) |

`POST /api/ingest`:

```json
{"source": "owncloud", "app_id": "ab12cd34ef", "app_name": "shop",
 "events": [{"t": 1763650000.1, "ip": "203.0.113.7", "method": "GET", "path": "/.env", "user_agent": "curl/8",
             "kind": "env-file", "status": 200, "username": null, "password": null, "canary": null}]}
```

`kind` ∈ `env-file, git-config, cloud-credentials, imds, actuator, wp-login, phpmyadmin, server-status,
db-dump, backup, credential-post, canary-use, blocked`. `canary` is the canary value that was used (for
`canary-use`). Events are grouped into sessions per `(app_id, ip)` with a 30-minute idle gap. Each request
becomes a "command" (`"GET /.env"`), each credential post an auth attempt, each canary use a canary alert.

Verdict (also the shape of each item in `/api/sessions`, plus `events` / `report` there):

```json
{"session_id": "…", "app_id": "…", "ip": "…", "source": "owncloud", "started": "…", "last_seen": "…",
 "requests": 5, "risk_score": 85, "threat_level": "CRITICAL", "classification": "AUTOMATED_BOT",
 "confidence": 0.9, "mitre": [{"id": "T1552.001", "name": "…", "tactic": "…"}], "canary_triggered": true,
 "recommend_block": true, "geo": {"country": "…", "city": "…", "source": "synthetic"}, "sealed": true}
```

`recommend_block` is true when `risk_score ≥ 60`, a canary was used, or credentials were posted.

## Router (per app, `control-plane/app/router/router.py`)

The control plane writes two extra files next to `routes.json`:

- `/config/security.json`: `{"decoys": true, "blocked": ["203.0.113.7"], "canaries": {"api_key": "…",
  "aws_access_key_id": "…", "aws_secret_access_key": "…", "jwt_secret": "…"}, "honey_dump": "…sql…"}`
- `/config/preheat.json`: `{"regions": {"lisbon": {"until": 1763650000, "event": "…", "paths": ["/"]}}}`

Decoys answer only paths no real app serves (`/.env`, `/.git/*`, `/.aws/credentials`, `/wp-login.php`,
`/phpmyadmin/*`, `/actuator/*`, `/latest/meta-data/*`, `/server-status`, `*.sql` dumps, …). Blocked IPs get 403
on every app. Any request carrying a canary value is recorded as `canary-use`. Events go to `metrics.json` as
`threats` (with a sequence number, so the control plane reads only new ones); preheat results as `preheat`.
