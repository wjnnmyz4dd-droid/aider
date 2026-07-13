"""Configuration for the Portfolio Statistical Risk Engine (Phase 2D).

Every threshold, schedule, and limit used anywhere in this package is
named here -- no magic numbers embedded in the computation modules
(CLAUDE.md §3). The confidence-scaling schedule is owned exclusively by
this package (ADR-027 Hard Rule 3) and is fully configurable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .models import ConfidenceTier

RISK_ENGINE_VERSION = "1.0.0-phase2d"

#: The task's own example schedule, verbatim: 65-69=0.25R, 70-74=0.50R,
#: 75-79=0.75R, 80-89=1.00R, 90-100=1.25R. Configurable -- replace this
#: tuple to change the schedule; nothing else in this package hardcodes it.
DEFAULT_CONFIDENCE_SCHEDULE: Tuple[ConfidenceTier, ...] = (
    ConfidenceTier(label="TIER_1", min_score=65.0, max_score=69.999, base_r=0.25),
    ConfidenceTier(label="TIER_2", min_score=70.0, max_score=74.999, base_r=0.50),
    ConfidenceTier(label="TIER_3", min_score=75.0, max_score=79.999, base_r=0.75),
    ConfidenceTier(label="TIER_4", min_score=80.0, max_score=89.999, base_r=1.00),
    ConfidenceTier(label="TIER_5", min_score=90.0, max_score=100.0, base_r=1.25),
)


@dataclass(frozen=True)
class RiskEngineConfig:
    # -- 65-point hard gate (ADR-027 Hard Rule 1) --
    minimum_evidence_score: float = 65.0

    # -- Confidence scaling (ADR-027 Hard Rule 3) --
    confidence_schedule: Tuple[ConfidenceTier, ...] = DEFAULT_CONFIDENCE_SCHEDULE
    #: Sizing is capped at this tier's base_r whenever trade history is
    #: insufficient to justify anything larger (ADR-027 §0a fail-closed rule).
    fail_closed_tier_index: int = 0

    # -- Portfolio risk / safety limits --
    portfolio_heat_limit_r: float = 6.0
    max_concurrent_risk_r: float = 6.0
    max_correlated_risk_r: float = 3.0
    daily_risk_limit_r: float = 3.0
    weekly_risk_limit_r: float = 6.0
    monthly_risk_limit_r: float = 10.0
    max_open_positions: int = 10
    max_positions_per_pair: int = 2
    max_currency_exposure_r: float = 4.0

    # -- Correlation --
    #: Static, documented approximation used when no rolling-correlation
    #: sample is available: pairs sharing a currency are treated as
    #: correlated at this coefficient (same-currency heuristic).
    shared_currency_correlation_estimate: float = 0.7
    high_correlation_threshold: float = 0.7
    negative_correlation_threshold: float = -0.7
    #: Minimum overlapping closed-trade samples, per pair, required
    #: before a *measured* rolling correlation replaces the static
    #: same-currency estimate.
    min_samples_for_rolling_correlation: int = 10
    rolling_correlation_window: int = 20

    # -- Statistics (ADR-027 §0a fail-closed rule) --
    min_trade_history_for_statistics: int = 20
    statistics_window: int = 100  # "rolling" window, in trades, for expectancy/Sharpe/Sortino/drawdown/etc.
    var_confidence: float = 0.95
    risk_of_ruin_ruin_threshold_r: float = -10.0  # cumulative R defined as "ruin"
    risk_of_ruin_simulations: int = 2000

    # -- Monte Carlo (advisory only, seeded -- ADR-027 Hard Rule 7) --
    monte_carlo_seed: int = 20260710
    monte_carlo_simulations: int = 1000
    monte_carlo_sequence_length: int = 100

    # -- Volatility-adjusted sizing --
    expansion_sizing_multiplier: float = 0.75
    compression_sizing_multiplier: float = 0.85
    abnormal_volatility_sizing_multiplier: float = 0.5
    normal_volatility_sizing_multiplier: float = 1.0
    abnormal_volatility_score_threshold: float = 90.0
    low_liquidity_score_threshold: float = 40.0
    low_liquidity_sizing_multiplier: float = 0.75

    # -- Position sizing --
    kelly_fraction_cap: float = 0.25  # fractional Kelly -- never full Kelly
    kelly_max_r: float = 1.0
    max_position_r: float = 1.25
    min_position_r: float = 0.1
    lot_step: float = 0.01
    r_to_lot_multiplier: float = 1.0  # placeholder unit scale; real balance-aware
    # lot sizing belongs to the Execution Validator / MT5 Bridge stages, out of
    # scope for this engine (ADR-027 §1)

    def confidence_tier_for_score(self, score: float) -> Optional[ConfidenceTier]:
        for tier in self.confidence_schedule:
            if tier.min_score <= score <= tier.max_score:
                return tier
        return None

    @property
    def fail_closed_tier(self) -> ConfidenceTier:
        return self.confidence_schedule[self.fail_closed_tier_index]


__all__ = ["RISK_ENGINE_VERSION", "DEFAULT_CONFIDENCE_SCHEDULE", "RiskEngineConfig"]
