"""Configuration for the News Provider Failover layer (Phase 3E,
ADR-033 Part 2). Every threshold is named here, never a magic number
embedded in `failover.py`/`providers/*.py` (CLAUDE.md SS3)."""

from __future__ import annotations

from dataclasses import dataclass

NEWS_INGESTION_VERSION = "1.0.0"


@dataclass(frozen=True)
class NewsIngestionConfig:
    #: Environment variable *names* -- the actual key is read from the
    #: environment at call time, never stored here, never logged
    #: (CLAUDE.md security model / ADR-033 SS6).
    trading_economics_api_key_env_var: str = "TITAN_PROTOCOL_TRADING_ECONOMICS_API_KEY"
    forex_factory_api_key_env_var: str = ""  # optional -- Forex Factory's public calendar needs none by default

    trading_economics_base_url: str = "https://api.tradingeconomics.com"
    forex_factory_base_url: str = ""

    request_timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0

    #: A provider's last successful fetch older than this is stale --
    #: it stops being TRUSTED even if it hasn't yet raised an error.
    stale_after_seconds: float = 900.0

    #: Consecutive successful fetches Trading Economics must produce
    #: before the engine switches back to it from Forex Factory --
    #: deterministic recovery, never a single lucky success (ADR-033
    #: SS4.2, avoids flapping).
    recovery_health_check_count: int = 3

    #: Bounded cache of normalized events, oldest evicted first
    #: (mirrors `market_intelligence.engine._NewsFeedCache`'s own
    #: bounded-cache pattern).
    cache_max_entries: int = 200

    def __post_init__(self) -> None:
        if not self.trading_economics_api_key_env_var.strip():
            raise ValueError("trading_economics_api_key_env_var must name an environment variable")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if self.recovery_health_check_count < 1:
            raise ValueError("recovery_health_check_count must be >= 1")
        if self.cache_max_entries < 1:
            raise ValueError("cache_max_entries must be >= 1")


__all__ = ["NEWS_INGESTION_VERSION", "NewsIngestionConfig"]
