"""Data models for the Market Data Ingestion layer (Phase 3C, ADR-033).

Every type here describes a raw broker fact or a validation/health
result derived from one -- nothing here is a trade decision, and
nothing here is the type Evidence Engine actually consumes
(`titan_protocol.evidence_engine.models.Bar`, unmodified and untouched). See
`normalization.py` for the one-way conversion at the seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

SCHEMA_VERSION = 1


class Timeframe(Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


#: Nominal bar interval in seconds -- used for staleness defaults and
#: missing-bar (gap) detection. Not a guarantee any broker delivers
#: exactly on this cadence; only a reference the config's own
#: thresholds are computed from.
TIMEFRAME_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}


class RejectionReason(Enum):
    MALFORMED = "MALFORMED"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
    UNKNOWN_TIMEFRAME = "UNKNOWN_TIMEFRAME"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    OUT_OF_SEQUENCE = "OUT_OF_SEQUENCE"
    CLOCK_SKEW = "CLOCK_SKEW"


@dataclass(frozen=True)
class RawBar:
    """Exactly what the mission's own field list names -- the raw,
    not-yet-trusted broker fact this layer receives, before any
    validation."""

    symbol: str
    timeframe: Timeframe
    broker_timestamp: datetime
    source_timestamp: datetime
    bar_open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool
    sequence_number: int
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass(frozen=True)
class TickEvent:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float


@dataclass(frozen=True)
class IngestionResult:
    accepted: bool
    rejection_reason: Optional[RejectionReason] = None
    reason_detail: str = ""
    gap_detected: bool = False


@dataclass(frozen=True)
class WarmupStatus:
    symbol: str
    timeframe: Timeframe
    bars_received: int
    bars_required: int
    ready: bool


@dataclass(frozen=True)
class FeedFreshness:
    symbol: str
    timeframe: Timeframe
    last_bar_open_time: Optional[datetime]
    is_stale: bool


@dataclass(frozen=True)
class MarketFeedHealthSnapshot:
    generated_at: datetime
    warmup_statuses: Tuple[WarmupStatus, ...]
    freshness: Tuple[FeedFreshness, ...]
    reasons: Tuple[str, ...]


__all__ = [
    "SCHEMA_VERSION",
    "Timeframe",
    "TIMEFRAME_SECONDS",
    "RejectionReason",
    "RawBar",
    "TickEvent",
    "IngestionResult",
    "WarmupStatus",
    "FeedFreshness",
    "MarketFeedHealthSnapshot",
]
