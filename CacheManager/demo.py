"""
Demo script — simulates the AI module writing predictions
and shows the cache module reacting in real time.

Usage:
    python demo.py
"""
import json
import time
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

PREDICTIONS_FILE = Path(__file__).parent / "data" / "predictions.json"


def make_prediction(offset_minutes: int = 60) -> dict:
    """Generate a fresh prediction with event starting in `offset_minutes`."""
    event_start = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "predictions": [
            {
                "id": f"pred-demo-{int(time.time())}",
                "region": "eu-west-1",
                "event_type": "football_match",
                "event_name": f"Demo Match (starts in {offset_minutes}min)",
                "event_start": event_start.isoformat(),
                "lead_time_minutes": max(5, offset_minutes - 5),
                "confidence": round(random.uniform(0.80, 0.99), 2),
                "expected_load_multiplier": round(random.uniform(2.0, 6.0), 1),
                "services": [
                    {
                        "name": "streaming_video",
                        "platforms": ["DAZN", "SportTV"],
                        "priority": 1.0,
                        "cache_size_mb": 256,
                        "content_keys": []
                    },
                    {
                        "name": "social_media",
                        "platforms": ["Twitter"],
                        "priority": 0.7,
                        "cache_size_mb": 64,
                        "content_keys": []
                    }
                ]
            }
        ]
    }


def write_prediction(offset_minutes: int = 60):
    pred = make_prediction(offset_minutes)
    PREDICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREDICTIONS_FILE.write_text(json.dumps(pred, indent=2))
    print(f"✍️  Wrote prediction: event in {offset_minutes} min | "
          f"confidence={pred['predictions'][0]['confidence']}")


if __name__ == "__main__":
    print("🎬 Cache Intelligence Demo")
    print("=" * 50)
    print("This script simulates the AI module writing predictions.")
    print("Start the cache service (python main.py) in another terminal.")
    print("=" * 50)

    # Scenario 1: Event in 2 hours
    print("\n[1/3] Writing prediction: event in 2 hours...")
    write_prediction(120)
    time.sleep(5)

    # Scenario 2: Urgent — event in 10 minutes (should trigger immediate warm)
    print("\n[2/3] Writing prediction: URGENT — event in 10 minutes!")
    write_prediction(10)
    time.sleep(5)

    # Scenario 3: Multiple regions
    print("\n[3/3] Writing multi-region prediction...")
    pred = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "predictions": [
            {
                "id": "pred-multi-eu",
                "region": "eu-west-1",
                "event_type": "football_match",
                "event_name": "Champions League Final",
                "event_start": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
                "lead_time_minutes": 30,
                "confidence": 0.99,
                "expected_load_multiplier": 8.0,
                "services": [
                    {
                        "name": "streaming_video",
                        "platforms": ["HBO Max", "DAZN", "Sky Sports"],
                        "priority": 1.0,
                        "cache_size_mb": 1024,
                        "content_keys": []
                    }
                ]
            },
            {
                "id": "pred-multi-us",
                "region": "us-east-1",
                "event_type": "football_match",
                "event_name": "Champions League Final (US broadcast)",
                "event_start": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
                "lead_time_minutes": 30,
                "confidence": 0.99,
                "expected_load_multiplier": 4.5,
                "services": [
                    {
                        "name": "streaming_video",
                        "platforms": ["Paramount+", "CBS Sports"],
                        "priority": 1.0,
                        "cache_size_mb": 512,
                        "content_keys": []
                    }
                ]
            }
        ]
    }
    PREDICTIONS_FILE.write_text(json.dumps(pred, indent=2))
    print(f"✍️  Wrote multi-region prediction (eu-west-1 + us-east-1)")

    print("\n✅ Demo predictions written.")
    print("Check http://localhost:8001/status and http://localhost:8001/plan")
