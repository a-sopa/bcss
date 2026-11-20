#!/usr/bin/env python3
"""
Google Gemini AI Integration Module for Intelligent Event Analysis
and Cache Manager Directive Generation.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import requests

log = logging.getLogger("prewarm.gemini")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def is_gemini_active() -> bool:
    return bool(GEMINI_API_KEY)


def _heuristic_fallback_analysis(event: Any) -> Dict[str, Any]:
    """Fallback heuristics used when GEMINI_API_KEY is not set or network fails."""
    desc = getattr(event, "description", "").lower()
    base_effect = float(getattr(event, "effect", 0.5))

    category = "other"
    traffic_pattern = "sustained_surge"
    cache_strategy = "standard"
    ttl = 900
    routes = ["/api/v1/feed", "/api/v1/status"]
    confidence = 0.75
    reasoning = "Heuristic fallback analysis based on keyword pattern."

    if any(k in desc for k in ["black friday", "cyber monday", "campaign", "promo", "launch"]):
        category = "commercial"
        traffic_pattern = "sustained_surge"
        cache_strategy = "aggressive_precache"
        ttl = 3600
        routes = ["/api/v1/products", "/api/v1/catalog", "/api/v1/promotions", "/api/v1/checkout"]
        confidence = 0.90
        reasoning = "High-volume commercial event; aggressive pre-caching of catalog and checkout is recommended."
    elif any(k in desc for k in ["vs", "cl", "pl", "derby", "football", "champions", "cup", "league"]):
        category = "sports"
        traffic_pattern = "pre_event_surge"
        cache_strategy = "stale_while_revalidate"
        ttl = 300
        routes = ["/api/v1/live", "/api/v1/scoreboard", "/api/v1/stream", "/api/v1/news"]
        confidence = 0.85
        reasoning = "Live sports match causes sharp spikes before kickoff, during halftime, and immediately post-match."
    elif any(k in desc for k in ["concert", "festival", "show", "stadium", "arena", "tour"]):
        category = "music_culture"
        traffic_pattern = "post_event_spike"
        cache_strategy = "aggressive_precache"
        ttl = 1800
        routes = ["/api/v1/tickets", "/api/v1/venues", "/api/v1/schedule"]
        confidence = 0.80
        reasoning = "Cultural/entertainment event with heavy ticket verification and venue check requests."
    elif any(k in desc for k in ["strike", "protest", "storm", "alert", "disruption"]):
        category = "regional_disruption"
        traffic_pattern = "sustained_surge"
        cache_strategy = "dynamic_bypass"
        ttl = 120
        routes = ["/api/v1/alerts", "/api/v1/transit", "/api/v1/news"]
        confidence = 0.85
        reasoning = "Public disruption creates continuous demand for real-time status updates."

    return {
        "category": category,
        "traffic_pattern": traffic_pattern,
        "adjusted_effect": round(base_effect, 2),
        "confidence": confidence,
        "reasoning": reasoning,
        "cache_strategy": cache_strategy,
        "recommended_ttl_seconds": ttl,
        "pre_warm_routes": routes,
        "analyzed_by": "local_heuristic",
    }


def analyze_events_with_gemini(events: List[Any]) -> List[Dict[str, Any]]:
    """Analyzes events using Gemini AI LLM. Falls back cleanly to heuristics if key is unset."""
    if not events:
        return []

    if not GEMINI_API_KEY:
        log.info("Gemini AI: GEMINI_API_KEY not set. Using local heuristic analysis (set GEMINI_API_KEY to enable LLM).")
        results = []
        for ev in events:
            analysis = _heuristic_fallback_analysis(ev)
            analysis["event_description"] = ev.description
            analysis["country"] = ev.country
            analysis["start_utc"] = ev.start.isoformat()
            analysis["end_utc"] = ev.end.isoformat()
            analysis["source"] = getattr(ev, "source", "unknown")
            results.append(analysis)
        return results

    simplified_events = [
        {
            "id": idx,
            "description": ev.description,
            "country": ev.country,
            "start_utc": ev.start.isoformat(),
            "end_utc": ev.end.isoformat(),
            "initial_estimated_effect": ev.effect,
            "source": getattr(ev, "source", "unknown"),
        }
        for idx, ev in enumerate(events)
    ]

    prompt = f"""
You are a cloud infrastructure, server capacity, and HTTP/Redis caching specialist for digital services in Europe.

Analyze the following list of European regional and national events to assess their infrastructure traffic impact and cache requirements:
{json.dumps(simplified_events, indent=2, ensure_ascii=False)}

For EACH event (matching its 'id'), return a JSON object with:
- "id": event id
- "category": one of ["sports", "music_culture", "commercial", "regional_disruption", "social_political", "other"]
- "traffic_pattern": one of ["pre_event_surge", "in_event_dip", "post_event_spike", "sustained_surge"]
- "adjusted_effect": float between -1.0 and 3.0 (e.g. 0.8 means +80% traffic, -0.4 means 40% drop)
- "confidence": float between 0.0 and 1.0
- "reasoning": 1 concise sentence explanation
- "cache_strategy": one of ["aggressive_precache", "stale_while_revalidate", "dynamic_bypass", "standard"]
- "recommended_ttl_seconds": integer (e.g. 120, 300, 1800, 3600)
- "pre_warm_routes": list of 2-4 API route patterns to pre-load into cache

Return a JSON array of objects.
"""
    endpoint = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }

    try:
        log.info("Gemini AI: Analyzing %d events via model %s...", len(events), GEMINI_MODEL)
        resp = requests.post(endpoint, headers=headers, json=body, timeout=25)
        resp.raise_for_status()
        raw_items = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
        ai_map = {item["id"]: item for item in raw_items if "id" in item}

        results = []
        for idx, ev in enumerate(events):
            item_ai = ai_map.get(idx) or _heuristic_fallback_analysis(ev)
            item_ai["analyzed_by"] = f"gemini_{GEMINI_MODEL}"
            item_ai["event_description"] = ev.description
            item_ai["country"] = ev.country
            item_ai["start_utc"] = ev.start.isoformat()
            item_ai["end_utc"] = ev.end.isoformat()
            item_ai["source"] = getattr(ev, "source", "unknown")
            results.append(item_ai)

        log.info("Gemini AI: Event analysis completed successfully.")
        return results

    except Exception as e:
        log.warning("Gemini AI request failed (%s). Falling back to heuristic analysis.", e)
        results = []
        for ev in events:
            analysis = _heuristic_fallback_analysis(ev)
            analysis["event_description"] = ev.description
            analysis["country"] = ev.country
            analysis["start_utc"] = ev.start.isoformat()
            analysis["end_utc"] = ev.end.isoformat()
            analysis["source"] = getattr(ev, "source", "unknown")
            results.append(analysis)
        return results


def export_to_cache_manager(
    output_path: os.PathLike,
    now: Any,
    deployments_result: Dict[str, Any],
    analyzed_events: List[Dict[str, Any]],
    dry_run: bool = True,
) -> None:
    """Exports structured JSON file for consumption by the downstream cache manager."""
    zone_directives = {}

    for dep_name, dep_data in deployments_result.items():
        zone_events = [
            ev for ev in analyzed_events
            if ev.get("country") in dep_data.get("covered_countries", [])
        ]

        dominant_strategy = "standard"
        recommended_ttl = 900
        routes_to_warm = set()

        if dep_data.get("multiplier", 1.0) >= 1.5:
            dominant_strategy = "aggressive_precache"
            recommended_ttl = 3600
        elif dep_data.get("multiplier", 1.0) >= 1.2:
            dominant_strategy = "stale_while_revalidate"
            recommended_ttl = 1800

        for ze in zone_events:
            for r in ze.get("pre_warm_routes", []):
                routes_to_warm.add(r)
            if ze.get("cache_strategy") == "aggressive_precache":
                dominant_strategy = "aggressive_precache"
                recommended_ttl = max(recommended_ttl, ze.get("recommended_ttl_seconds", 1800))

        zone_directives[dep_name] = {
            "aws_region": dep_data.get("aws_region"),
            "function": dep_data.get("function"),
            "prewarm_status": "peak_expected" if dep_data.get("multiplier", 1.0) > 1.2 else "normal",
            "traffic_multiplier": dep_data.get("multiplier", 1.0),
            "target_lambda_concurrency": dep_data.get("target_pc", 0),
            "current_lambda_concurrency": dep_data.get("current_pc", 0),
            "cache_directive": {
                "recommended_strategy": dominant_strategy,
                "recommended_ttl_seconds": recommended_ttl,
                "stale_while_revalidate_seconds": 120,
                "pre_warm_routes": sorted(list(routes_to_warm)),
                "eviction_priority": "protect_hot_routes",
            },
        }

    cache_document = {
        "timestamp_utc": now.isoformat(),
        "generator_version": "2.0-gemini-ai",
        "dry_run": dry_run,
        "ai_status": {
            "gemini_active": is_gemini_active(),
            "model": GEMINI_MODEL if is_gemini_active() else "heuristic_fallback",
        },
        "deployments": zone_directives,
        "processed_events": analyzed_events,
        "cache_manager_instructions": {
            "recommended_action": "warm_cache_for_peak_zones",
            "lead_time_minutes": 20,
            "description": "Ready-to-consume directives for HTTP/Redis cache_manager.",
        },
    }

    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache_document, indent=2, ensure_ascii=False))
        log.info("Cache Manager: Exported directives successfully to %s", path)
    except OSError as e:
        log.error("Cache Manager: Failed to save JSON file (%s)", e)
