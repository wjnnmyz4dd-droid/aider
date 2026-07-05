"""Data Pipeline output objects (ADR-013 §5, INTERFACE_SPECIFICATION.md §1).

Every object here is an immutable (frozen) dataclass, carries
`schema_version` and `trace_id`, and is structurally incapable of
holding a trade idea, score, risk/compliance/execution decision, or
portfolio decision (ADR-013 §5's type-level guarantee) — see
tests/phantom_pipeline/data_pipeline/test_boundary.py for the
enforcement test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

SCHEMA_VERSION = 1


class DataQuality(Enum):
    """Per-record quality flag (ADR-013 §7). Never a numeric score."""

    NOMINAL = "NOMINAL"
    WARM_UP = "WARM_UP"
    GAP = "GAP"
    STALE = "STALE"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class NormalizedTick:
    """A single normalized tick (ADR-013 §5)."""

    schema_version: int
    trace_id: str
    symbol: str
    timestamp: datetime
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[float]
    source: str


@dataclass(frozen=True)
class NormalizedBar:
    """A single OHLCV bar (ADR-013 §5).

    `is_repaired` is part of the interface per ADR-013 §7's gap-repair
    disclosure requirement, but Phase 1 never sets it True — Phase 1
    detects gaps only; repair is out of scope (see gaps.py).
    """

    schema_version: int
    trace_id: str
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quality: DataQuality
    is_repaired: bool
    source: str


@dataclass(frozen=True)
class MarketSnapshot:
    """The shared, instant-in-time object multiple stages consume (ADR-013 §5, §9)."""

    schema_version: int
    trace_id: str
    symbol: str
    timestamp: datetime
    price: float
    spread: float
    market_status: str


@dataclass(frozen=True)
class DataQualityReport:
    """Completeness/freshness/latency/continuity/confidence assessment (ADR-013 §7).

    `latency_seconds` is `None` when it cannot be honestly measured —
    Phase 1 has no live broker feed adapter yet (that arrives with a real
    MT5 Broker Feed connection, ADR-015 §6), so there is no genuine
    ingestion-receipt timestamp to measure against a bar's own timestamp
    for historical/replay/synthetic input. Reporting a fabricated number
    here would violate the "never fabricate" discipline this ADR
    inherits from ADR-002 §10 — `None` is the honest value until a real
    feed supplies a receipt time (§6, `received_at`).
    """

    schema_version: int
    trace_id: str
    symbol: str
    timeframe: str
    window_start: datetime
    window_end: datetime
    completeness: float
    freshness_seconds: float
    latency_seconds: Optional[float]
    continuity: bool
    confidence: str
    gap_count: int
    duplicate_count: int
    out_of_order_count: int


@dataclass(frozen=True)
class PipelineHealth:
    """This stage's own operational health signal (ADR-013 §5), the input
    Watchdog (ADR-011) observes for this stage."""

    schema_version: int
    trace_id: str
    timestamp: datetime
    status: str
    reason: Optional[str]
    ticks_processed: int
    bars_produced: int
    gap_count: int


@dataclass(frozen=True)
class HistoricalSeries:
    """A bounded historical OHLCV series for a symbol/timeframe (ADR-013 §5)."""

    schema_version: int
    trace_id: str
    symbol: str
    timeframe: str
    bars: Tuple[NormalizedBar, ...]


@dataclass(frozen=True)
class ReplaySeries:
    """A captured sequence of historical ticks/bars, replayable through the
    same ingestion path (ADR-013 §5, §10)."""

    schema_version: int
    trace_id: str
    symbol: str
    ticks: Tuple[NormalizedTick, ...]
    bars: Tuple[NormalizedBar, ...]
