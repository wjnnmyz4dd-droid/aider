"""Configuration for the Evidence Engine (Phase 2A).

Every threshold and weight used anywhere in this package is named here
-- no magic numbers embedded in the computation modules (CLAUDE.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .models import SessionName

EVIDENCE_ENGINE_VERSION = "1.0.0-phase2a"


@dataclass(frozen=True)
class EvidenceEngineConfig:
    # -- Market structure --
    swing_lookback: int = 2  # bars required on each side to confirm a swing
    internal_structure_lookback: int = 5  # swings considered "internal" scope
    support_resistance_tolerance_pct: float = 0.05  # % price tolerance for level clustering
    support_resistance_min_touches: int = 2

    # -- Liquidity --
    equal_level_tolerance_pct: float = 0.05  # % price tolerance for "equal" highs/lows
    equal_level_min_points: int = 2
    displacement_atr_multiple: float = 1.5  # bar range vs ATR to count as displacement

    # -- Candlesticks --
    doji_body_to_range_max: float = 0.1  # body/range ratio below which a candle is a doji
    marubozu_wick_to_range_max: float = 0.05  # wick/range ratio below which a candle is a marubozu
    long_body_to_range_min: float = 0.6  # body/range ratio for a "long body" candle
    small_body_to_range_max: float = 0.3  # body/range ratio for a "small body" candle

    # -- Volatility --
    atr_period: int = 14
    volatility_expansion_ratio: float = 1.3  # current ATR / average ATR above which = expansion
    volatility_compression_ratio: float = 0.7  # current ATR / average ATR below which = compression

    # -- Session (UTC hour boundaries, half-open [start, end)) --
    asian_session_start_hour: int = 0
    asian_session_end_hour: int = 8
    london_session_start_hour: int = 7
    london_session_end_hour: int = 16
    new_york_session_start_hour: int = 12
    new_york_session_end_hour: int = 21
    london_new_york_overlap_start_hour: int = 12
    london_new_york_overlap_end_hour: int = 16
    early_new_york_end_hour: int = 18  # [overlap_end, early_new_york_end) = early NY

    # -- Evidence scoring weights (must sum to 1.0; validated in __post_init__) --
    structure_weight: float = 0.25
    liquidity_weight: float = 0.15
    candlestick_weight: float = 0.15
    trend_weight: float = 0.20
    volatility_weight: float = 0.10
    session_weight: float = 0.10
    indicator_weight: float = 0.05

    # -- Indicator cache --
    indicator_cache_max_entries: int = 512

    # -- Support/resistance context (Amendment 1) --
    psychological_level_increment: float = 0.0050  # round-number spacing (FX 4/5-digit convention)
    psychological_level_count: int = 3  # levels generated above and below the current price
    confluence_tolerance_pct: float = 0.05  # % price tolerance for clustering S/R sources together
    confluence_full_score_source_count: int = 4  # distinct sources agreeing for a confluence_score of 100
    break_quality_default_score: float = 50.0  # neutral score when no structure event exists yet to assess
    break_quality_atr_reference_multiple: float = 2.0  # confirming-bar-range/ATR ratio for a 100 score
    false_break_probability_default: float = 0.3  # no sweep observed yet -- moderate, not zero, uncertainty
    false_break_probability_trap: float = 0.8  # most recent sweep was classified a trap
    false_break_probability_confirmed: float = 0.15  # most recent sweep had genuine displacement follow-through

    # -- Opening range (ADR-035 §3, Phase 0 -- ADR-024 Amendment 2) --
    #: (session, start_hour_utc, start_minute_utc) per configured anchor.
    #: () = none configured -- fail closed until an operator configures one.
    opening_range_anchors: Tuple[Tuple[SessionName, int, int], ...] = ()
    opening_range_duration_minutes: int = 30
    opening_range_min_bars: int = 3
    #: Expected spacing between consecutive closed bars, for this
    #: package's own independent temporal-gap check (ADR-035 §3) -- never
    #: imported from `market_data_ingestion`'s `Timeframe`/`TIMEFRAME_SECONDS`,
    #: since Evidence Engine has no existing dependency on that package.
    #: Not empirically validated against real market data yet (ADR-035
    #: §18.B) -- an operator must configure this to match the actual bar
    #: timeframe Evidence Engine is fed.
    expected_bar_interval_seconds: int = 300

    def __post_init__(self) -> None:
        total = (
            self.structure_weight
            + self.liquidity_weight
            + self.candlestick_weight
            + self.trend_weight
            + self.volatility_weight
            + self.session_weight
            + self.indicator_weight
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Evidence score component weights must sum to 1.0, got {total}")
        if not (0 < self.opening_range_duration_minutes <= 1440):
            raise ValueError(
                f"opening_range_duration_minutes must be within (0, 1440], got {self.opening_range_duration_minutes}"
            )
        if self.opening_range_min_bars < 1:
            raise ValueError(f"opening_range_min_bars must be >= 1, got {self.opening_range_min_bars}")
        if self.expected_bar_interval_seconds <= 0:
            raise ValueError(
                f"expected_bar_interval_seconds must be > 0, got {self.expected_bar_interval_seconds}"
            )
        _validate_no_overlapping_anchors(self.opening_range_anchors, self.opening_range_duration_minutes)


def _validate_no_overlapping_anchors(
    anchors: Tuple[Tuple[SessionName, int, int], ...], duration_minutes: int
) -> None:
    """Rejects any two configured anchors whose `[range_start, range_end)`
    windows would coincide or overlap (ADR-035 §3's "Identification"
    rule requires this for `OpeningRangeState` to be disambiguated by its
    own window rather than by `session` alone)."""
    windows = []
    for hour, minute in ((a[1], a[2]) for a in anchors):
        start = hour * 60 + minute
        windows.append((start, start + duration_minutes))
    for i in range(len(windows)):
        start_i, end_i = windows[i]
        for j in range(i + 1, len(windows)):
            start_j, end_j = windows[j]
            if start_i < end_j and start_j < end_i:
                raise ValueError(
                    f"opening_range_anchors[{i}] and opening_range_anchors[{j}] "
                    "produce coincident or overlapping windows"
                )


__all__ = ["EVIDENCE_ENGINE_VERSION", "EvidenceEngineConfig"]
