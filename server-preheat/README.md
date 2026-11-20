# server-preheat

Standalone **Server Pre-Heating Engine** for cloud and local infrastructure.

## What it does

1. **Capacity Scaling** – adjusts provisioned concurrency / instance count per zone based on predicted traffic multipliers from `scraper-ai`.
2. **Active Warm-up** – dispatches parallel synthetic HTTP probes (or AWS Lambda invocations) to initialize JIT runtimes, in-memory caches, and database connection pools before real user traffic arrives.

## Usage

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server-preheat"))
from preheat_engine import ServerPreheatEngine

engine = ServerPreheatEngine(dry_run=True)  # dry_run=False for live AWS
telemetry = engine.preheat_zone(
    zone_name="eu-west",
    dep_config={"aws_region": "eu-west-1", "function": "my-api", "alias": "live"},
    target_capacity=40,
    multiplier=2.5,
)
print(telemetry)
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `1` | Set to `0` to execute real AWS API calls |
| `HYSTERESIS` | `0.15` | Minimum capacity delta (%) before re-scaling |
| `SERVER_WARMUP_URLS` | `` | Comma-separated HTTP endpoints to probe (for VMs/containers) |

## Dependencies

- `requests` (HTTP warmup probes)
- `boto3` *(optional)* – only needed for real AWS Lambda provisioned concurrency

## Integration

This module is consumed by `scraper-ai/main.py` after Gemini AI analysis produces per-zone traffic multipliers. It is intentionally **decoupled** from both `scraper-ai` and `CacheManager`.
