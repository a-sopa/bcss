"""
Configuration settings for the Cache Intelligence Module.
"""
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # Predictions file (shared with AI module)
    predictions_file: Path = Path(__file__).parent / "data" / "predictions.json"

    # Cache warming defaults
    default_ttl_seconds: int = 7200          # 2 hours base TTL
    lead_time_buffer_seconds: int = 300      # Warm 5 min before scheduled lead time
    max_cache_size_mb_per_region: int = 2048 # Max Redis memory per region

    # Scheduler
    watcher_poll_seconds: int = 10           # How often to re-read predictions file
    warm_check_interval_seconds: int = 30    # Scheduler tick
    critic_interval_seconds: int = 300       # Self-critic evaluation interval (5 min)

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8001

    # Logging
    log_level: str = "INFO"

    class Config:
        env_prefix = "CACHE_"
        env_file = ".env"


settings = Settings()
