"""Market Data Ingestion (Phase 3C, ADR-033) -- receives, validates,
normalizes, orders, and warms up live MT5 market data for the frozen,
unmodified Evidence Engine. Owns transport/validation/normalization/
ordering/freshness/deduplication/warmup only -- never interprets
market data (Evidence Engine remains the sole authority for that)."""

from __future__ import annotations

from .config import MARKET_DATA_INGESTION_VERSION, MarketDataIngestionConfig
from .engine import MarketDataIngestionEngine
from .freshness import is_stale
from .metrics import MarketDataIngestionMetrics
from .models import (
    SCHEMA_VERSION,
    TIMEFRAME_SECONDS,
    FeedFreshness,
    IngestionResult,
    MarketFeedHealthSnapshot,
    RawBar,
    RejectionReason,
    TickEvent,
    Timeframe,
    WarmupStatus,
)
from .normalization import normalize
from .ordering import SequenceState, advance, check_ordering
from .validation import validate_bar
from .warmup import WarmupTracker

__all__ = [
    "SCHEMA_VERSION",
    "MARKET_DATA_INGESTION_VERSION",
    "Timeframe",
    "TIMEFRAME_SECONDS",
    "RejectionReason",
    "RawBar",
    "TickEvent",
    "IngestionResult",
    "WarmupStatus",
    "FeedFreshness",
    "MarketFeedHealthSnapshot",
    "MarketDataIngestionConfig",
    "MarketDataIngestionEngine",
    "MarketDataIngestionMetrics",
    "is_stale",
    "normalize",
    "validate_bar",
    "SequenceState",
    "check_ordering",
    "advance",
    "WarmupTracker",
]
