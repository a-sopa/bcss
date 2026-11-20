#!/usr/bin/env python3
"""
Autonomous Integration Bridge
Connects `scraper-ai` (AI Traffic & Concurrency Engine) and `CacheManager` (Redis & Self-Critic Engine)
WITHOUT modifying any line of original code in either project.

Workflow:
  1. Checks for CacheManager Self-Critic feedback (data/feedback.json).
  2. Executes scraper-ai pipeline to collect real events, query Gemini AI, and preheat cloud capacity.
  3. Formats and relays generated directives into CacheManager/data/predictions.json.
  4. Triggers CacheManager planner / watcher to update the Redis warming plan.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BRIDGE] %(levelname)s %(message)s")
log = logging.getLogger("bridge")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = REPO_ROOT / "scraper-ai"
CACHE_DIR = REPO_ROOT / "CacheManager"

FEED_FILE = SCRAPER_DIR / "cache_manager_feed.json"
PREDICTIONS_TARGET = CACHE_DIR / "data" / "predictions.json"
FEEDBACK_SOURCE = CACHE_DIR / "data" / "feedback.json"
FEEDBACK_DEST = SCRAPER_DIR / "feedback.json"


def check_directories():
    if not SCRAPER_DIR.exists():
        log.error("Directory scraper-ai not found at %s", SCRAPER_DIR)
        return False
    if not CACHE_DIR.exists():
        log.error("Directory CacheManager not found at %s", CACHE_DIR)
        return False
    return True


def relay_feedback():
    """Relays feedback from CacheManager Self-Critic to scraper-ai."""
    if FEEDBACK_SOURCE.exists():
        try:
            fb = json.loads(FEEDBACK_SOURCE.read_text(encoding="utf-8"))
            failed_count = len(fb.get("failed_regions", []))
            log.info("Relaying Self-Critic feedback (%d failed regions) to scraper-ai...", failed_count)
            shutil.copy2(FEEDBACK_SOURCE, FEEDBACK_DEST)
            return True
        except Exception as e:
            log.warning("Could not relay feedback: %s", e)
    return False


def run_scraper_ai():
    """Executes the scraper-ai pipeline."""
    log.info("Executing scraper-ai engine (Event collection + Gemini analysis + Cloud pre-heat)...")
    env = os.environ.copy()
    env["CACHE_MANAGER_OUTPUT"] = str(FEED_FILE)
    res = subprocess.run(
        [sys.executable, str(SCRAPER_DIR / "main.py")],
        cwd=str(SCRAPER_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        log.error("scraper-ai failed with code %d:\n%s", res.returncode, res.stderr)
        return False

    log.info("scraper-ai completed successfully.")
    return True


def relay_predictions_to_cache_manager():
    """Reads scraper-ai feed, ensures deployment country metadata is present, and writes to CacheManager."""
    if not FEED_FILE.exists():
        log.error("Feed file %s was not generated.", FEED_FILE)
        return False

    try:
        data = json.loads(FEED_FILE.read_text(encoding="utf-8"))

        # Country mapping for European deployments if missing
        zone_country_mapping = {
            "eu-west": ["PT", "ES", "FR", "BE", "NL", "LU"],
            "eu-central": ["DE", "AT", "CH", "PL", "CZ", "SK", "HU"],
            "eu-north": ["GB", "IE", "SE", "NO", "DK", "FI", "IS", "EE", "LV", "LT"],
            "eu-south": ["IT", "GR", "RO", "BG", "TR", "CY", "MT", "UA", "MD", "RS", "HR", "BA", "ME", "MK", "AL", "SI", "XK"],
        }

        deployments = data.get("deployments", {})
        for dep_name, dep_data in deployments.items():
            if "covered_countries" not in dep_data and dep_name in zone_country_mapping:
                dep_data["covered_countries"] = zone_country_mapping[dep_name]

        PREDICTIONS_TARGET.parent.mkdir(parents=True, exist_ok=True)
        PREDICTIONS_TARGET.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Relayed and synchronized feed into CacheManager: %s", PREDICTIONS_TARGET)
        return True
    except Exception as e:
        log.error("Error relaying predictions: %s", e)
        return False


def run_full_bridge_cycle():
    """Runs a complete synchronized cycle between both modules."""
    log.info("Starting Autonomous Bridge Cycle...")
    if not check_directories():
        return False

    # Step 1: Pass past feedback to scraper
    relay_feedback()

    # Step 2: Run scraper-ai
    if not run_scraper_ai():
        return False

    # Step 3: Deliver predictions to CacheManager
    if not relay_predictions_to_cache_manager():
        return False

    log.info("Bridge cycle finished: CacheManager is now armed with live AI predictions.")
    return True


if __name__ == "__main__":
    success = run_full_bridge_cycle()
    sys.exit(0 if success else 1)
