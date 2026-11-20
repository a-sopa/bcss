"""
Extensibility & Resilience Test Suite

Validates that:
1. Standard prediction files load without issues.
2. The Gemini AI format from scraper-ai (cache_manager_feed.json with deployments & processed_events)
   is parsed seamlessly.
3. Unexpected/extra fields injected into events or services do NOT cause validation errors.
4. Fast O(1) hit/miss indexing behaves correctly.
"""
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, ".")

from models.prediction import PredictionFile
from services.cache_planner import CachePlanner
from services.cache_warmer import CacheWarmer

print("🧪 Starting Extensibility & Robustness Tests...")

# ─── Test 1: Standard Format ────────────────────────────────────────────────
with open("data/predictions.json") as f:
    standard_data = json.load(f)

pred_std = PredictionFile.from_raw_json(standard_data)
assert len(pred_std.predictions) > 0, "Standard predictions should load"
print(f"✅ Test 1 Passed: Standard format loaded ({len(pred_std.predictions)} events)")


# ─── Test 2: Gemini AI / scraper-ai Feed Format (cache_manager_feed.json) ──
gemini_feed_sample = {
    "timestamp_utc": "2026-11-20T11:21:02.000Z",
    "generator_version": "2.0-gemini-ai",
    "dry_run": True,
    "ai_status": {
        "gemini_active": True,
        "model": "gemini-2.5-flash",
    },
    "deployments": {
        "eu-south": {
            "aws_region": "eu-south-1",
            "function": "api-gateway",
            "prewarm_status": "peak_expected",
            "traffic_multiplier": 1.9,
            "target_lambda_concurrency": 250,
            "current_lambda_concurrency": 50,
            "covered_countries": ["PT", "ES"],
            "cache_directive": {
                "recommended_strategy": "aggressive_precache",
                "recommended_ttl_seconds": 3600,
                "stale_while_revalidate_seconds": 120,
                "pre_warm_routes": ["/api/v1/live", "/api/v1/scoreboard", "/api/v1/stream"],
                "eviction_priority": "protect_hot_routes",
            },
        },
        "eu-west": {
            "aws_region": "eu-west-1",
            "function": "web-ingress",
            "traffic_multiplier": 1.4,
            "covered_countries": ["GB", "DE"],
            "cache_directive": {
                "recommended_strategy": "stale_while_revalidate",
                "recommended_ttl_seconds": 1800,
                "pre_warm_routes": ["/api/v1/catalog", "/api/v1/promotions"],
            },
        },
    },
    "processed_events": [
        {
            "id": 0,
            "event_description": "UEFA Champions League / European Derby Live Stream",
            "country": "PT",
            "start_utc": "2026-11-20T18:30:00Z",
            "end_utc": "2026-11-20T22:30:00Z",
            "category": "sports",
            "traffic_pattern": "pre_event_surge",
            "adjusted_effect": 0.95,
            "confidence": 0.95,
            "reasoning": "High viewership in Southern Europe.",
            "cache_strategy": "stale_while_revalidate",
            "recommended_ttl_seconds": 1800,
            "pre_warm_routes": ["/api/v1/live", "/api/v1/stream"],
            "analyzed_by": "gemini_2.5_flash",
            # Extra fields from future AI models:
            "historical_peak_viewers": 1500000,
            "weather_forecast": "Rainy (higher indoor streaming expected)",
            "sentiment_score": 0.88,
        }
    ],
    "cache_manager_instructions": {
        "recommended_action": "warm_cache_for_peak_zones",
        "lead_time_minutes": 45,
        "description": "Ready-to-consume directives for HTTP/Redis cache_manager.",
    },
}

pred_gemini = PredictionFile.from_raw_json(gemini_feed_sample)
assert len(pred_gemini.predictions) > 0, "Gemini feed should be converted into predictions"
print(f"✅ Test 2 Passed: Gemini AI feed adapted ({len(pred_gemini.predictions)} region events)")

planner = CachePlanner()
plan_gemini = planner.build_plan(pred_gemini)
assert "eu-south-1" in plan_gemini.region_plans or "eu-south" in plan_gemini.region_plans
print("✅ Test 2b Passed: CachePlanner generated plan from Gemini AI feed")


# ─── Test 3: Unforeseen Extra Fields (Resilience) ──────────────────────────
heavily_modified_event = {
    "generated_at": "2026-11-20T12:00:00Z",
    "predictions": [
        {
            "id": "pred-extreme-test",
            "region": "ap-southeast-1",
            "event_type": "esports_final",
            "event_name": "League of Legends Worlds Finals",
            "event_start": "2026-11-20T16:00:00Z",
            "lead_time_minutes": 60,
            "confidence": 0.98,
            "expected_load_multiplier": 7.5,
            "services": [
                {
                    "name": "streaming_video",
                    "platforms": ["Twitch", "YouTube Gaming"],
                    "priority": 1.0,
                    "cache_size_mb": 1024,
                    "content_keys": ["/live/finals/master.m3u8"],
                    # Extra fields:
                    "encoding_profiles": ["1080p60", "4k"],
                    "cdn_provider": "Cloudflare",
                }
            ],
            # Extra event metadata from AI:
            "ticket_sales": 50000,
            "sponsors": ["Mercedes", "Mastercard"],
            "ai_submodel": "deepseek-r1-enhanced",
            "estimated_bandwidth_gbps": 420.5,
        }
    ],
    "system_telemetry": {
        "global_datacenter_status": "nominal",
    },
}

pred_extra = PredictionFile.from_raw_json(heavily_modified_event)
assert pred_extra.predictions[0].model_extra["ticket_sales"] == 50000
assert pred_extra.predictions[0].services[0].model_extra["cdn_provider"] == "Cloudflare"
print("✅ Test 3 Passed: Extra fields safely preserved without schema rejection")


# ─── Test 4: Fast O(1) Indexing in Warmer ──────────────────────────────────
warmer = CacheWarmer()
warmer.update_plan(plan_gemini)
test_key = list(warmer._entry_index.keys())[0]

warmer.record_hit(test_key)
warmer.record_hit(test_key)
warmer.record_miss(test_key)
entry = warmer._entry_index[test_key]
assert entry.hit_count == 2
assert entry.miss_count == 1
assert entry.hit_rate == round(2 / 3, 4)

print(f"✅ Test 4 Passed: O(1) hit/miss tracking verified on key '{test_key}'")

print("\n🎉 ALL EXTENSIBILITY AND EFFICIENCY TESTS PASSED!")
