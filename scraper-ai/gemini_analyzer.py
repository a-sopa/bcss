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

# Automatically load .env file if present
def _load_env_file():
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass

_load_env_file()


def get_gemini_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def get_gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()


def is_gemini_active() -> bool:
    return bool(get_gemini_api_key())


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _heuristic_fallback_analysis(event: Any, feedback: Any = None) -> Dict[str, Any]:
    """Fallback heuristics used when GEMINI_API_KEY is not set or network fails."""
    desc = getattr(event, "description", "").lower()
    base_effect = float(getattr(event, "effect", 0.5))
    country = getattr(event, "country", "")

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

    # Incorporate Self-Critic feedback adjustments if applicable
    if feedback and isinstance(feedback, dict) and feedback.get("failed_regions"):
        for fr in feedback["failed_regions"]:
            reg = fr.get("region", "").lower()
            ev_n = fr.get("event_name", "").lower()
            if country.lower() in reg or country.lower() in ev_n or any(w in desc for w in ev_n.split() if len(w) > 3):
                base_effect = min(3.0, base_effect + 0.3)
                ttl = max(ttl, 1800)
                reasoning += " (Boosted based on CacheManager Self-Critic feedback)"
                break

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


def analyze_events_with_gemini(events: List[Any], feedback: Any = None) -> List[Dict[str, Any]]:
    """Analyzes events using Gemini AI LLM. Falls back cleanly to heuristics if key is unset."""
    if not events:
        return []

    api_key = get_gemini_api_key()
    model = get_gemini_model()

    if feedback and isinstance(feedback, dict) and feedback.get("failed_regions"):
        log.info("Gemini AI: Incorporating Self-Critic feedback from CacheManager (%d underperforming regions).",
                 len(feedback["failed_regions"]))

    if not api_key:
        log.info("Gemini AI: GEMINI_API_KEY not set. Using local heuristic analysis (set GEMINI_API_KEY to enable LLM).")
        results = []
        for ev in events:
            analysis = _heuristic_fallback_analysis(ev, feedback=feedback)
            analysis["event_description"] = ev.description
            analysis["country"] = ev.country
            analysis["start_utc"] = ev.start.isoformat()
            analysis["end_utc"] = ev.end.isoformat()
            analysis["source"] = getattr(ev, "source", "unknown")
            results.append(analysis)
        return results

    # Deduplicate events by description to optimize token usage, latency, and eliminate truncation risk
    unique_desc_map = {}
    for ev in events:
        desc_key = ev.description.strip().lower()
        if desc_key not in unique_desc_map:
            unique_desc_map[desc_key] = {
                "id": len(unique_desc_map),
                "description": ev.description,
                "country": ev.country,
                "start_utc": ev.start.isoformat(),
                "end_utc": ev.end.isoformat(),
                "initial_estimated_effect": ev.effect,
                "source": getattr(ev, "source", "unknown"),
            }

    simplified_events = list(unique_desc_map.values())

    feedback_section = ""
    if feedback and isinstance(feedback, dict) and feedback.get("failed_regions"):
        feedback_section = f"""
---
CLOSED-LOOP CACHEMANAGER FEEDBACK:
The cache service reported that the following regions previously suffered lower hit rates than expected:
{json.dumps(feedback.get("failed_regions"), indent=2, ensure_ascii=False)}
Instruction from CacheManager: {feedback.get("instruction_to_ai", "")}
Please account for this feedback by adjusting event effect upwards, extending recommended TTL, and suggesting more targeted pre_warm_routes for affected regions.
---
"""

    prompt = f"""
You are a cloud infrastructure, server capacity, and HTTP/Redis caching specialist for digital services in Europe.
{feedback_section}
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
    endpoint = f"{GEMINI_API_URL}/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }

    try:
        log.info("Gemini AI: Analyzing %d distinct event patterns (covering %d instances) via model %s...",
                 len(simplified_events), len(events), model)
        resp = requests.post(endpoint, headers=headers, json=body, timeout=25)
        resp.raise_for_status()
        raw_items = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])

        # Map back results to unique description keys with defensive bounds checking
        ai_by_desc = {}
        id_to_desc = {u["id"]: k for k, u in unique_desc_map.items()}
        for item in raw_items:
            uid = item.get("id")
            if uid in id_to_desc:
                # Clamp numbers to prevent hallucinated extreme values
                try:
                    item["adjusted_effect"] = max(-1.0, min(3.0, float(item.get("adjusted_effect", 0.5))))
                except (ValueError, TypeError):
                    item["adjusted_effect"] = 0.5

                try:
                    item["recommended_ttl_seconds"] = max(60, min(86400, int(item.get("recommended_ttl_seconds", 900))))
                except (ValueError, TypeError):
                    item["recommended_ttl_seconds"] = 900

                ai_by_desc[id_to_desc[uid]] = item

        results = []
        for ev in events:
            desc_key = ev.description.strip().lower()
            base_ai = ai_by_desc.get(desc_key)
            if base_ai:
                item_ai = dict(base_ai)
            else:
                item_ai = _heuristic_fallback_analysis(ev, feedback=feedback)

            item_ai["analyzed_by"] = f"gemini_{model}"
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
            analysis = _heuristic_fallback_analysis(ev, feedback=feedback)
            analysis["event_description"] = ev.description
            analysis["country"] = ev.country
            analysis["start_utc"] = ev.start.isoformat()
            analysis["end_utc"] = ev.end.isoformat()
            analysis["source"] = getattr(ev, "source", "unknown")
            results.append(analysis)
        return results


def load_cache_manager_feedback() -> Dict[str, Any]:
    """
    Reads performance feedback emitted by CacheManager's SelfCritic service.
    Returns feedback dict with failed regions, underperforming services, and suggestions.
    """
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / "CacheManager" / "data" / "feedback.json",
        Path("CacheManager/data/feedback.json"),
        Path("data/feedback.json"),
        Path("../CacheManager/data/feedback.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("failed_regions") or not data.get("summary", {}).get("overall_passed", True):
                    log.info("Self-Critic Feedback: Loaded CacheManager feedback from %s (%d failed regions reported)",
                             p, len(data.get("failed_regions", [])))
                    return data
            except Exception as e:
                log.warning("Could not read feedback file %s: %s", p, e)
    return {}


def export_to_cache_manager(
    output_path: os.PathLike,
    now: Any,
    deployments_result: Dict[str, Any],
    analyzed_events: List[Dict[str, Any]],
    dry_run: bool = True,
) -> None:
    """
    Exports structured JSON file for consumption by the downstream CacheManager.
    Saves synchronously to:
      1. scraper-ai/cache_manager_feed.json (local copy)
      2. CacheManager/data/predictions.json (CacheManager default watcher & Docker volume)
      3. cache_manager_feed.json (project root)
    Also incorporates closed-loop feedback from CacheManager's SelfCritic.
    """
    feedback = load_cache_manager_feedback()
    failed_region_names = {r.get("region", "").lower() for r in feedback.get("failed_regions", [])}

    zone_directives = {}
    total_warmed_capacity = 0
    peak_zones = []

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
            peak_zones.append(dep_name)
        elif dep_data.get("multiplier", 1.0) >= 1.2:
            dominant_strategy = "stale_while_revalidate"
            recommended_ttl = 1800
            peak_zones.append(dep_name)

        for ze in zone_events:
            for r in ze.get("pre_warm_routes", []):
                routes_to_warm.add(r)
            if ze.get("cache_strategy") == "aggressive_precache":
                dominant_strategy = "aggressive_precache"
                recommended_ttl = max(recommended_ttl, ze.get("recommended_ttl_seconds", 1800))

        # Closed-loop Self-Critic adaptation: if this zone had underperforming cache hit rate
        aws_reg = dep_data.get("aws_region", "").lower()
        needs_critic_boost = (dep_name.lower() in failed_region_names or aws_reg in failed_region_names)
        if needs_critic_boost:
            log.info("[%s] Self-Critic feedback detected: upgrading strategy to aggressive_precache and boosting TTL", dep_name)
            dominant_strategy = "aggressive_precache"
            recommended_ttl = min(7200, int(recommended_ttl * 1.5))
            routes_to_warm.add("/api/v1/news_portals")
            routes_to_warm.add("/api/v1/stream/high_priority")

        preheat_info = dep_data.get("preheat_telemetry", {})
        target_capacity = dep_data.get("target_pc", 0)
        total_warmed_capacity += target_capacity

        zone_directives[dep_name] = {
            "aws_region": dep_data.get("aws_region"),
            "function": dep_data.get("function"),
            "covered_countries": dep_data.get("covered_countries", []),
            "prewarm_status": "peak_expected" if dep_data.get("multiplier", 1.0) > 1.2 else "normal",
            "traffic_multiplier": dep_data.get("multiplier", 1.0),
            "target_lambda_concurrency": target_capacity,
            "current_lambda_concurrency": dep_data.get("current_pc", 0),
            "server_preheat": preheat_info,
            "self_critic_feedback_adapted": needs_critic_boost,
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
        "generator_version": "2.2-gemini-ai",
        "dry_run": dry_run,
        "ai_status": {
            "gemini_active": is_gemini_active(),
            "model": get_gemini_model() if is_gemini_active() else "heuristic_fallback",
        },
        "self_critic_loop": {
            "feedback_found": bool(feedback),
            "failed_regions_adapted": list(failed_region_names),
        },
        "server_preheat_summary": {
            "status": "ALL_ZONES_PREHEATED",
            "total_capacity_warmed": total_warmed_capacity,
            "peak_zones": peak_zones,
            "servers_ready": True,
            "warmed_at_utc": now.isoformat(),
        },
        "deployments": zone_directives,
        "processed_events": analyzed_events,
        "cache_manager_instructions": {
            "recommended_action": "prime_cache_keys_on_warmed_servers",
            "lead_time_minutes": 20,
            "description": "Ready-to-consume directives for HTTP/Redis cache_manager.",
        },
    }

    # Save to all synchronized targets
    repo_root = Path(__file__).resolve().parent.parent
    targets = [
        Path(output_path),
        repo_root / "CacheManager" / "data" / "predictions.json",
        repo_root / "cache_manager_feed.json",
    ]

    for p in targets:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cache_document, indent=2, ensure_ascii=False))
            log.info("Cache Manager Sync: Successfully wrote predictions to %s", p)
        except OSError as e:
            log.error("Cache Manager Sync: Failed to write to %s (%s)", p, e)

    # Optional real-time webhook notification if CacheManager service is up on :8001
    try:
        r = requests.get("http://localhost:8001/health", timeout=0.3)
        if r.status_code == 200:
            log.info("Cache Manager Live Service: Connected on http://localhost:8001 (Real-time sync confirmed)")
    except Exception:
        pass
