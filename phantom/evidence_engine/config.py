"""Configuration for the Evidence Engine (Phase 2A).

Every threshold and weight used anywhere in this package is named here
-- no magic numbers embedded in the computation modules (CLAUDE.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["EVIDENCE_ENGINE_VERSION", "EvidenceEngineConfig"]
