"""
Prediction Watcher — monitors the shared JSON file written by the AI module
and triggers cache planning when new predictions arrive.
"""
from __future__ import annotations
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from models.prediction import PredictionFile
from config import settings

logger = logging.getLogger(__name__)


class PredictionWatcher:
    """
    Polls the predictions JSON file for changes.
    When the AI writes new predictions, this service picks them up
    and notifies registered callbacks.
    """

    def __init__(self):
        self._path: Path = settings.predictions_file
        self._last_mtime: float = 0.0
        self._last_generated_at: datetime | None = None
        self._current_predictions: PredictionFile | None = None
        self._callbacks: list = []
        self._lock = threading.Lock()

    def register_callback(self, fn):
        """Register a function to be called when predictions are updated."""
        self._callbacks.append(fn)

    @property
    def current_predictions(self) -> PredictionFile | None:
        with self._lock:
            return self._current_predictions

    def _resolve_path(self) -> Path | None:
        """Finds the active predictions file (configured, or teammate's feed)."""
        candidates = [
            self._path,
            Path("data/predictions.json"),
            Path("../cache_manager_feed.json"),
            Path("cache_manager_feed.json"),
            Path("../scraper-ai/cache_manager_feed.json"),
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def check(self) -> bool:
        """
        Check if the predictions file has changed.
        Returns True if new predictions were loaded.
        """
        active_path = self._resolve_path()
        if not active_path:
            logger.debug(f"Predictions file not found at {self._path} or known locations")
            return False

        try:
            mtime = active_path.stat().st_mtime
            if mtime <= self._last_mtime and self._current_predictions is not None:
                return False  # No change

            raw = active_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            predictions = PredictionFile.from_raw_json(data)

            # Avoid re-processing the same prediction batch
            if (
                self._last_generated_at is not None
                and predictions.generated_at == self._last_generated_at
            ):
                self._last_mtime = mtime
                return False

            with self._lock:
                self._current_predictions = predictions
                self._last_generated_at = predictions.generated_at
                self._last_mtime = mtime

            logger.info(
                f"📡 New predictions loaded: {len(predictions.predictions)} events "
                f"(generated at {predictions.generated_at.isoformat()})"
            )

            # Notify all registered callbacks
            for cb in self._callbacks:
                try:
                    cb(predictions)
                except Exception as exc:
                    logger.error(f"Callback {cb.__name__} failed: {exc}")

            return True

        except json.JSONDecodeError as exc:
            logger.error(f"Invalid JSON in predictions file: {exc}")
        except Exception as exc:
            logger.error(f"Error reading predictions file: {exc}")

        return False
