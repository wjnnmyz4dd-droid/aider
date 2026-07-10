"""Data models for the Portfolio Statistical Risk Engine (Phase 2D).

Every type here is either a plain, immutable record of portfolio/history
fact supplied by a caller (`OpenPosition`, `TradeResult`), or a computed
risk evaluation of one. Nothing here is a trade decision: there is no
`BUY`/`SELL` enum, no order type, no execution method anywhere in this
module, by design (see
`docs/adr/ADR-027-portfolio-statistical-risk-engine.md` Hard Rule 9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from phantom.strategy_engine.models import StrategyId

SCHEMA_VERSION = 1


class RejectionReason(Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_QUALIFIED_STRATEGY = "NO_QUALIFIED_STRATEGY"
    PORTFOLIO_HEAT_EXCEEDED = "PORTFOLIO_HEAT_EXCEEDED"
    CORRELATION_LIMIT_EXCEEDED = "CORRELATION_LIMIT_EXCEEDED"
    DAILY_RISK_LIMIT_EXCEEDED = "DAILY_RISK_LIMIT_EXCEEDED"
    WEEKLY_RISK_LIMIT_EXCEEDED = "WEEKLY_RISK_LIMIT_EXCEEDED"
    MONTHLY_RISK_LIMIT_EXCEEDED = "MONTHLY_RISK_LIMIT_EXCEEDED"
    MAX_OPEN_POSITIONS_EXCEEDED = "MAX_OPEN_POSITIONS_EXCEEDED"
    MAX_POSITIONS_PER_PAIR_EXCEEDED = "MAX_POSITIONS_PER_PAIR_EXCEEDED"
    MAX_CURRENCY_EXPOSURE_EXCEEDED = "MAX_CURRENCY_EXPOSURE_EXCEEDED"


class DataQuality(Enum):
    """Whether the computation behind a field had real data to work
    with. `UNKNOWN` is never silently treated as favorable -- it is the
    fail-closed signal (ADR-027 Hard Rule 6)."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class Direction(Enum):
    """An already-open position's side. Not a trade decision -- this
    engine never chooses a direction, it only reads one from a
    caller-supplied `OpenPosition` describing existing portfolio state."""

    LONG = "LONG"
    SHORT = "SHORT"


# -- Caller-supplied portfolio/history inputs (ADR-027 §0a) ----------------


@dataclass(frozen=True)
class OpenPosition:
    pair: str
    direction: Direction
    size_r: float  # risk allocated to this position, in R
    opened_at: datetime


@dataclass(frozen=True)
class PortfolioState:
    open_positions: Tuple[OpenPosition, ...] = ()


@dataclass(frozen=True)
class TradeResult:
    pair: str
    strategy_id: Optional[StrategyId]
    risk_r: float  # R allocated to this trade when it was taken
    r_multiple: float  # realized outcome, e.g. +2.0R, -1.0R
    opened_at: datetime
    closed_at: datetime
    won: bool


@dataclass(frozen=True)
class TradeHistory:
    results: Tuple[TradeResult, ...] = ()


# -- Portfolio exposure ------------------------------------------------------


@dataclass(frozen=True)
class ExposureSummary:
    portfolio_heat_r: float  # sum of all open + pending-reserved risk, in R
    long_exposure_r: float
    short_exposure_r: float
    net_exposure_r: float
    currency_exposure_r: Tuple[Tuple[str, float], ...]  # currency -> net R
    symbol_exposure_r: Tuple[Tuple[str, float], ...]  # symbol -> net R
    sector_exposure_r: Tuple[Tuple[str, float], ...]  # future-ready, empty today
    pending_reservation_total_r: float
    data_quality: DataQuality


# -- Correlation --------------------------------------------------------------


@dataclass(frozen=True)
class CorrelationStatus:
    pair_correlations: Tuple[Tuple[str, float], ...]  # other pair -> coefficient [-1, 1]
    correlation_clusters: Tuple[Tuple[str, ...], ...]
    highly_correlated_pairs: Tuple[str, ...]
    negatively_correlated_pairs: Tuple[str, ...]
    cross_currency_exposure_r: float
    limit_exceeded: bool
    reason: str
    data_quality: DataQuality


# -- Statistics ---------------------------------------------------------------


@dataclass(frozen=True)
class RMultipleSummary:
    mean: float
    std_dev: float
    best: float
    worst: float
    count: int


@dataclass(frozen=True)
class StatisticalMetrics:
    sufficient_data: bool
    sample_size: int
    rolling_expectancy: Optional[float] = None
    win_rate: Optional[float] = None
    loss_rate: Optional[float] = None
    risk_of_ruin: Optional[float] = None
    var_95: Optional[float] = None
    cvar_95: Optional[float] = None
    max_drawdown_estimate: Optional[float] = None
    recovery_factor: Optional[float] = None
    profit_factor: Optional[float] = None
    rolling_sharpe: Optional[float] = None
    rolling_sortino: Optional[float] = None
    calmar_ratio: Optional[float] = None
    ulcer_index: Optional[float] = None
    r_multiple_summary: Optional[RMultipleSummary] = None
    kelly_fraction: Optional[float] = None  # full Kelly f* = p - q/b; never applied unfractionalized


# -- Monte Carlo (advisory only) ---------------------------------------------


@dataclass(frozen=True)
class MonteCarloResult:
    simulations_run: int
    seed: int
    expected_drawdown: float
    expected_equity_low: float
    expected_equity_high: float
    confidence_intervals: Tuple[Tuple[int, float], ...]  # percentile -> equity (R)
    worst_case_drawdown: float
    risk_distribution_summary: str


# -- Volatility ---------------------------------------------------------------


@dataclass(frozen=True)
class VolatilityAdjustment:
    atr: float
    volatility_label: str
    sizing_multiplier: float  # applied to the confidence-tier base R
    reason: str


# -- Position sizing ------------------------------------------------------------


@dataclass(frozen=True)
class ConfidenceTier:
    label: str
    min_score: float
    max_score: float
    base_r: float


@dataclass(frozen=True)
class PositionSizeRecommendation:
    fixed_fractional_r: float
    confidence_scaled_r: float
    volatility_scaled_r: float
    kelly_r: Optional[float]
    final_r: float
    lot_size: float
    capped: bool
    cap_reason: Optional[str]


# -- Output ---------------------------------------------------------------


@dataclass(frozen=True)
class RiskSnapshot:
    """No execution, no compliance decision -- ever (ADR-027 Hard Rules
    1, 9, 10)."""

    pair: str
    generated_at: datetime
    approved: bool
    approved_risk_r: float
    recommended_position_size: Optional[PositionSizeRecommendation]
    confidence_tier: Optional[ConfidenceTier]
    exposure_summary: Optional[ExposureSummary]
    correlation_status: Optional[CorrelationStatus]
    statistical_metrics: Optional[StatisticalMetrics]
    monte_carlo: Optional[MonteCarloResult]
    reasons: Tuple[str, ...]
    warnings: Tuple[str, ...]
    rejection_reason: Optional[RejectionReason]
    reservation_id: Optional[str]


__all__ = [
    "SCHEMA_VERSION",
    "RejectionReason",
    "DataQuality",
    "Direction",
    "OpenPosition",
    "PortfolioState",
    "TradeResult",
    "TradeHistory",
    "ExposureSummary",
    "CorrelationStatus",
    "RMultipleSummary",
    "StatisticalMetrics",
    "MonteCarloResult",
    "VolatilityAdjustment",
    "ConfidenceTier",
    "PositionSizeRecommendation",
    "RiskSnapshot",
]
