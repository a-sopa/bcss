"""
Pydantic models for AI predictions received from the prediction file.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ServicePrediction(BaseModel):
    """A specific service/platform predicted to have high demand."""
    name: str = Field(..., description="Service category (e.g. 'streaming_video')")
    platforms: list[str] = Field(default_factory=list, description="Specific platforms (e.g. ['DAZN', 'Eleven'])")
    priority: float = Field(..., ge=0.0, le=1.0, description="Priority score 0-1 (1 = highest)")
    cache_size_mb: int = Field(default=256, description="Suggested cache allocation in MB")
    content_keys: list[str] = Field(
        default_factory=list,
        description="Specific cache keys to pre-warm (e.g. CDN URLs, API endpoints)"
    )


class EventPrediction(BaseModel):
    """A single event prediction from the AI module."""
    id: str = Field(..., description="Unique prediction ID")
    region: str = Field(..., description="Cloud region (e.g. 'eu-west-1')")
    event_type: str = Field(..., description="Type: football_match, concert, news_spike, etc.")
    event_name: str = Field(..., description="Human-readable event name")
    event_start: datetime = Field(..., description="When the event starts (UTC)")
    lead_time_minutes: int = Field(
        default=60,
        description="How many minutes before event_start to begin warming"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="AI confidence score")
    expected_load_multiplier: float = Field(
        default=2.0,
        description="Expected traffic increase multiplier (e.g. 4.5 = 450% of baseline)"
    )
    services: list[ServicePrediction] = Field(
        default_factory=list,
        description="Services to prioritize in cache"
    )

    @property
    def warm_at(self) -> datetime:
        """UTC datetime when cache warming should begin."""
        from datetime import timedelta
        return self.event_start - timedelta(minutes=self.lead_time_minutes)

    @property
    def ttl_seconds(self) -> int:
        """Cache TTL — keep hot until 30 min after event start."""
        from datetime import timedelta
        from config import settings
        duration = timedelta(minutes=self.lead_time_minutes + 90)
        return max(settings.default_ttl_seconds, int(duration.total_seconds()))


class PredictionFile(BaseModel):
    """Root schema of the JSON file written by the AI module."""
    generated_at: datetime = Field(..., description="When the AI generated these predictions")
    predictions: list[EventPrediction] = Field(default_factory=list)
