"""Configuration for the Market Data Ingestion layer (Phase 3C).

Every threshold is named here, never a magic number embedded in
validation.py/ordering.py/freshness.py/warmup.py (CLAUDE.md SS3).
`min_warmup_bars_by_timeframe`'s default (50, every timeframe) is a
conservative default with headroom over Evidence Engine's own real
lookback requirements (`EvidenceEngineConfig.internal_structure_
lookback = 5`, plus `support_resistance.py`'s clustering and
`volatility.py`'s ATR window both wanting more history than the bare
minimum swing count) -- not an arbitrary number (ADR-033 SS3.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from .models import Timeframe

MARKET_DATA_INGESTION_VERSION = "1.0.0"

_DEFAULT_ENABLED_PAIRS: Tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
)
_DEFAULT_REQUIRED_TIMEFRAMES: Tuple[Timeframe, ...] = (Timeframe.M15, Timeframe.H1)


def _default_min_warmup_bars() -> Dict[Timeframe, int]:
    return {tf: 50 for tf in Timeframe}


def _default_staleness_multiplier() -> Dict[Timeframe, float]:
    # Staleness threshold = this multiplier * TIMEFRAME_SECONDS[tf] --
    # generous headroom over the nominal bar cadence to avoid false
    # positives from ordinary broker/network latency, never so loose
    # that a genuinely dead feed goes undetected for multiple bars.
    return {tf: 2.5 for tf in Timeframe}


@dataclass(frozen=True)
class MarketDataIngestionConfig:
    enabled_pairs: Tuple[str, ...] = _DEFAULT_ENABLED_PAIRS
    required_timeframes: Tuple[Timeframe, ...] = _DEFAULT_REQUIRED_TIMEFRAMES

    min_warmup_bars_by_timeframe: Dict[Timeframe, int] = field(default_factory=_default_min_warmup_bars)
    staleness_multiplier_by_timeframe: Dict[Timeframe, float] = field(default_factory=_default_staleness_multiplier)

    #: A bar's own `bar_open_time`-to-`bar_open_time` gap above this
    #: multiple of the nominal interval is reported as a missing-bar
    #: gap (informational -- never itself a rejection reason).
    gap_detection_multiplier: float = 1.5

    max_clock_skew_seconds: float = 5.0
    max_bars_retained: int = 500
    spread_rolling_window: int = 20

    def __post_init__(self) -> None:
        if not self.enabled_pairs:
            raise ValueError("enabled_pairs must name at least one symbol")
        if not self.required_timeframes:
            raise ValueError("required_timeframes must name at least one timeframe")


__all__ = ["MARKET_DATA_INGESTION_VERSION", "MarketDataIngestionConfig"]
