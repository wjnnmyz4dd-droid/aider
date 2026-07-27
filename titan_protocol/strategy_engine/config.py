"""Configuration for the Strategy Engine (Phase 2C).

Every threshold and weight used anywhere in this package is named here
-- no magic numbers embedded in the strategy modules (CLAUDE.md §3). Per
`ADR-026` Hard Rule 5, `approved_pairs_by_strategy` is read-only at
runtime -- no method anywhere in this package mutates it; changing
eligibility means editing this config and redeploying.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .models import StrategyId

STRATEGY_ENGINE_VERSION = "1.0.0-phase2c"

# -- Per-strategy approved pair universes (ADR-026 §3, Strategy Eligibility
# Matrix). Liquidity Sweep and Session Breakout sets are exactly the pairs
# named in the user's own example. BOS+FVG and Trend Continuation have no
# example given -- reasonable, clearly-labeled defaults (core majors, plus
# JPY crosses for Trend Continuation, which historically trend well) are
# used pending real operator/Research-Engine-recommended tuning. Range
# Reversal's set is explicitly a placeholder ("pairs statistically shown to
# respect range conditions") since no real statistics exist yet -- never
# fabricated, always documented as provisional.

_LIQUIDITY_SWEEP_MSS_PAIRS: Tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
)
_BOS_FVG_PAIRS: Tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
)
_TREND_CONTINUATION_PAIRS: Tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY", "GBPJPY",
)
_SESSION_BREAKOUT_PAIRS: Tuple[str, ...] = ("EURUSD", "GBPUSD", "EURGBP", "GBPCHF")
_RANGE_REVERSAL_PAIRS: Tuple[str, ...] = ("AUDNZD", "EURCHF", "EURGBP", "GBPCHF")

DEFAULT_APPROVED_PAIRS_BY_STRATEGY: Tuple[Tuple[StrategyId, Tuple[str, ...]], ...] = (
    (StrategyId.LIQUIDITY_SWEEP_MSS, _LIQUIDITY_SWEEP_MSS_PAIRS),
    (StrategyId.BOS_FVG, _BOS_FVG_PAIRS),
    (StrategyId.TREND_CONTINUATION, _TREND_CONTINUATION_PAIRS),
    (StrategyId.SESSION_BREAKOUT, _SESSION_BREAKOUT_PAIRS),
    (StrategyId.RANGE_REVERSAL, _RANGE_REVERSAL_PAIRS),
)


@dataclass(frozen=True)
class StrategyEngineConfig:
    approved_pairs_by_strategy: Tuple[Tuple[StrategyId, Tuple[str, ...]], ...] = DEFAULT_APPROVED_PAIRS_BY_STRATEGY

    # -- Generic qualification thresholds, shared across strategies --
    strong_score_threshold: float = 70.0  # a ComponentScore/sub-factor at or above this counts as a "strength"
    weak_score_threshold: float = 30.0  # at or below this counts as a "weakness"

    # -- Liquidity Sweep + Market Structure Shift --
    liquidity_sweep_min_liquidity_score: float = 40.0
    liquidity_sweep_min_confidence: float = 0.5

    # -- BOS + Fair Value Gap --
    bos_fvg_min_structure_score: float = 50.0
    bos_fvg_min_confidence: float = 0.5

    # -- Trend Continuation --
    trend_continuation_min_trend_score: float = 65.0

    # -- Session Breakout --
    session_breakout_min_session_score: float = 70.0
    session_breakout_min_volatility_score: float = 55.0

    # -- Range Reversal --
    range_reversal_min_confluence_score: float = 50.0
    range_reversal_max_trend_score: float = 40.0  # a genuinely ranging market scores low on trend
    range_reversal_min_candlestick_confidence: float = 0.5

    # -- Selection cascade --
    score_tie_tolerance: float = 0.5  # scores within this margin are considered tied at a cascade step

    # -- Opening Range Breakout (ADR-035 §4/§13, Phase 2 Step 2B) --
    orb_min_breakout_distance_atr_multiple: float = 0.15  # min abs(close - range_boundary) / atr for a genuine breakout
    orb_min_body_to_range_ratio: float = 0.5  # min abs(close - open) / (high - low) on the breakout bar, rejects mostly-wick bars
    orb_min_confirmation_candles: int = 1  # consecutive closed bars required beyond the range boundary before qualifying
    orb_max_qualifications_per_range: int = 1  # lockout limit per (pair, range_start)

    # -- Opening Range Breakout FVG confirmation (ADR-035 §5/§13, Phase 3) --
    orb_fvg_max_age_bars: int = 10  # max bars between an FVG's formation (end_index) and the breakout candidate before it's too stale to confirm
    orb_fvg_min_size_atr_multiple: float = 0.1  # min (gap_high - gap_low) / atr for a qualifying FVG
    orb_fvg_score_weight: float = 0.15  # weight on the binary FVG-confirmation bonus; cross-field weight-sum bound is Phase 5's scope (ADR-035 §17), not validated here

    # -- Opening Range Breakout MI eligibility + range quality (ADR-035 §2/§13, Phase 4) --
    orb_min_range_atr_ratio: float = 0.5  # min (range_high - range_low) / atr for the opening range to be judged wide enough to be a real range, not noise
    orb_max_spread_pips: float = 3.0  # max pair_safety.liquidity.current_spread before the pair is judged untradeable this cycle
    orb_min_liquidity_score: float = 60.0  # min pair_safety.liquidity.liquidity_score (Market Intelligence's broker/spread-derived score, distinct from Evidence Engine's structural liquidity)

    def __post_init__(self) -> None:
        if self.orb_min_breakout_distance_atr_multiple <= 0:
            raise ValueError(
                f"orb_min_breakout_distance_atr_multiple must be > 0, got {self.orb_min_breakout_distance_atr_multiple}"
            )
        if not (0.0 <= self.orb_min_body_to_range_ratio <= 1.0):
            raise ValueError(
                f"orb_min_body_to_range_ratio must be within [0, 1], got {self.orb_min_body_to_range_ratio}"
            )
        if self.orb_min_confirmation_candles < 1:
            raise ValueError(
                f"orb_min_confirmation_candles must be >= 1, got {self.orb_min_confirmation_candles}"
            )
        if self.orb_max_qualifications_per_range < 1:
            raise ValueError(
                f"orb_max_qualifications_per_range must be >= 1, got {self.orb_max_qualifications_per_range}"
            )
        if self.orb_fvg_max_age_bars < 1:
            raise ValueError(
                f"orb_fvg_max_age_bars must be >= 1, got {self.orb_fvg_max_age_bars}"
            )
        if self.orb_fvg_min_size_atr_multiple <= 0:
            raise ValueError(
                f"orb_fvg_min_size_atr_multiple must be > 0, got {self.orb_fvg_min_size_atr_multiple}"
            )
        if not (0.0 <= self.orb_fvg_score_weight <= 1.0):
            raise ValueError(
                f"orb_fvg_score_weight must be within [0, 1], got {self.orb_fvg_score_weight}"
            )
        if self.orb_min_range_atr_ratio <= 0:
            raise ValueError(
                f"orb_min_range_atr_ratio must be > 0, got {self.orb_min_range_atr_ratio}"
            )
        if self.orb_max_spread_pips <= 0:
            raise ValueError(
                f"orb_max_spread_pips must be > 0, got {self.orb_max_spread_pips}"
            )
        if not (0.0 <= self.orb_min_liquidity_score <= 100.0):
            raise ValueError(
                f"orb_min_liquidity_score must be within [0, 100], got {self.orb_min_liquidity_score}"
            )

    def approved_pairs_for(self, strategy_id: StrategyId) -> Tuple[str, ...]:
        for sid, pairs in self.approved_pairs_by_strategy:
            if sid == strategy_id:
                return pairs
        return ()


__all__ = ["STRATEGY_ENGINE_VERSION", "DEFAULT_APPROVED_PAIRS_BY_STRATEGY", "StrategyEngineConfig"]
