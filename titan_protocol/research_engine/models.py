"""Data models for the Research & Learning Engine (Phase 2F).

Every type here is either a plain, immutable record of a closed
trade's full lifecycle supplied by a caller (`ClosedTrade`), or a
computed, read-only analysis of history. Nothing here is a trade
decision: there is no `BUY`/`SELL` enum, no order, no parameter
mutation, anywhere in this module, by design (see
`docs/adr/ADR-029-research-learning-engine.md` Hard Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Sequence, Tuple

from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.evidence_engine.models import CandlestickPattern, SessionName
from titan_protocol.market_intelligence.models import NewsCategory
from titan_protocol.risk_engine.models import StatisticalMetrics
from titan_protocol.strategy_engine.models import MarketRegime, StrategyId

SCHEMA_VERSION = 1


class SRInteraction(Enum):
    """How the trade related to support/resistance structure at entry
    -- a small, explicit taxonomy rather than free text, so attribution
    buckets are stable and comparable."""

    NONE = "NONE"
    CONFLUENCE_BOUNCE = "CONFLUENCE_BOUNCE"
    BREAK_CONTINUATION = "BREAK_CONTINUATION"
    FALSE_BREAK = "FALSE_BREAK"


class VolatilityBucket(Enum):
    NORMAL = "NORMAL"
    EXPANSION = "EXPANSION"
    COMPRESSION = "COMPRESSION"
    ABNORMAL = "ABNORMAL"


class TrendVsRange(Enum):
    TREND = "TREND"
    RANGE = "RANGE"


@dataclass(frozen=True)
class ClosedTrade:
    """One trade candidate's complete lifecycle -- caller-supplied,
    pre-aggregated (never derived from raw bars by this engine, ADR-029
    §3). Recorded for every trade the system considered, "approved,
    rejected, and executed" alike (the task's own words): the pipeline-
    context fields (pair, strategy, regime, scores, risk recommendation,
    compliance decision, `evaluated_at`) are always present; the
    execution-outcome fields (entry/exit/SL/TP/R-multiple/holding time/
    execution-quality facts) are `None` whenever the trade was rejected
    before it ever opened. `risk_r`/`r_multiple`/`opened_at`/`closed_at`/
    `won` mirror `titan_protocol.risk_engine.models.TradeResult`'s fields
    exactly when present, so an executed `ClosedTrade` converts to one
    without renaming (ADR-029 §0)."""

    pair: str
    strategy_id: Optional[StrategyId]
    market_regime: Optional[MarketRegime]
    trend_vs_range: Optional[TrendVsRange]

    evidence_score: float
    market_intelligence_score: float
    trade_readiness_score: float

    risk_confidence_tier: Optional[str]
    risk_r: float  # Risk Engine's original recommended R (0.0 if Risk Engine itself rejected)
    kelly_was_binding: bool
    portfolio_heat_at_entry_r: Optional[float]
    was_correlated_with_open_position: bool
    compliance_decision: Optional[ComplianceDecision]
    approved_size_r: float  # Compliance Engine's final approved R (0.0 if rejected)

    evaluated_at: datetime  # always present, even for a rejected trade
    session: Optional[SessionName]

    # -- Execution outcome -- None for every field below when the trade never opened --
    won: Optional[bool] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    r_multiple: Optional[float] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    requested_entry_price: Optional[float] = None
    slippage_entry_pips: Optional[float] = None
    slippage_exit_pips: Optional[float] = None
    spread_at_entry: Optional[float] = None
    spread_at_exit: Optional[float] = None
    time_to_fill_ms: Optional[float] = None
    partial_fills: int = 0
    requotes: int = 0

    news_category: Optional[NewsCategory] = None
    news_blackout_was_active: bool = False
    peg_policy_was_active: bool = False
    holiday_was_active: bool = False

    volatility_bucket: VolatilityBucket = VolatilityBucket.NORMAL
    candlestick_pattern: Optional[CandlestickPattern] = None
    support_resistance_interaction: SRInteraction = SRInteraction.NONE
    liquidity_sweep_occurred: bool = False
    bos_fvg_occurred: bool = False

    @property
    def was_executed(self) -> bool:
        return self.r_multiple is not None and self.opened_at is not None and self.closed_at is not None


@dataclass(frozen=True)
class ClosedTradeHistory:
    results: Tuple[ClosedTrade, ...] = ()


def executed_trades(trades: Sequence[ClosedTrade]) -> Tuple[ClosedTrade, ...]:
    """The subset that actually opened and closed -- rejected
    candidates carry no meaningful P&L/execution-quality facts to
    attribute or score (ADR-029 §3)."""

    return tuple(t for t in trades if t.was_executed)


class AttributionDimension(Enum):
    PAIR = "PAIR"
    STRATEGY = "STRATEGY"
    SESSION = "SESSION"
    REGIME = "REGIME"
    TREND_VS_RANGE = "TREND_VS_RANGE"
    NEWS_CATEGORY = "NEWS_CATEGORY"
    VOLATILITY_BUCKET = "VOLATILITY_BUCKET"
    CANDLESTICK_PATTERN = "CANDLESTICK_PATTERN"
    SR_INTERACTION = "SR_INTERACTION"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    BOS_FVG = "BOS_FVG"
    TIME_OF_DAY = "TIME_OF_DAY"
    DAY_OF_WEEK = "DAY_OF_WEEK"


@dataclass(frozen=True)
class AttributionBucket:
    key: str
    sample_size: int
    total_r: float
    statistics: StatisticalMetrics


@dataclass(frozen=True)
class PerformanceAttribution:
    dimension: AttributionDimension
    buckets: Tuple[AttributionBucket, ...]


@dataclass(frozen=True)
class Ranking:
    """Shared shape for pair/strategy/session rankings -- one type,
    three thin builders (CLAUDE.md §6)."""

    key: str
    rank: int  # 1 = best
    sample_size: int
    statistics: StatisticalMetrics
    average_hold_time_seconds: float


@dataclass(frozen=True)
class ExecutionQualityRecord:
    pair: str
    slippage_score: float
    fill_time_score: float
    requote_penalty: float
    stop_execution_quality: float
    tp_execution_quality: float
    composite_score: float


@dataclass(frozen=True)
class ExecutionQualitySummary:
    overall_score: float
    average_slippage_pips: float
    average_time_to_fill_ms: float
    total_requotes: int
    total_partial_fills: int
    per_pair_score: Tuple[Tuple[str, float], ...]


@dataclass(frozen=True)
class EffectivenessComparison:
    label: str
    baseline_sample_size: int
    baseline_expectancy: Optional[float]
    comparison_sample_size: int
    comparison_expectancy: Optional[float]
    delta: Optional[float]
    notable: bool


@dataclass(frozen=True)
class MarketIntelligenceReview:
    news_blackout_effectiveness: EffectivenessComparison
    peg_protection_effectiveness: EffectivenessComparison
    holiday_restriction_effectiveness: EffectivenessComparison
    liquidity_scoring_effectiveness: Tuple[EffectivenessComparison, ...]
    session_scoring_effectiveness: Tuple[EffectivenessComparison, ...]
    recommendations: Tuple[str, ...]


@dataclass(frozen=True)
class RiskReview:
    confidence_scaling_effectiveness: Tuple[EffectivenessComparison, ...]
    volatility_scaling_effectiveness: Tuple[EffectivenessComparison, ...]
    kelly_cap_effectiveness: EffectivenessComparison
    portfolio_heat_effectiveness: Tuple[EffectivenessComparison, ...]
    recommendations: Tuple[str, ...]


@dataclass(frozen=True)
class ComplianceEffectiveness:
    approve_vs_reduce: EffectivenessComparison
    rejection_count: int
    rejection_rate: float
    recommendations: Tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    text: str
    supporting_dimension: str
    supporting_data: str
    confidence: str  # "LOW" / "MEDIUM" / "HIGH", based on sample size


class ReportPeriod(Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class ResearchSnapshot:
    """No trade decision, no execution, no parameter mutation -- ever
    (ADR-029 Hard Rule 1)."""

    generated_at: datetime
    period: ReportPeriod
    period_start: datetime
    period_end: datetime
    sample_size: int

    pair_rankings: Tuple[Ranking, ...]
    strategy_rankings: Tuple[Ranking, ...]
    session_rankings: Tuple[Ranking, ...]
    attributions: Tuple[PerformanceAttribution, ...]
    execution_quality: ExecutionQualitySummary
    market_intelligence_review: MarketIntelligenceReview
    risk_review: RiskReview
    compliance_effectiveness: ComplianceEffectiveness
    recommendations: Tuple[Recommendation, ...]
    warnings: Tuple[str, ...]


__all__ = [
    "SCHEMA_VERSION",
    "SRInteraction",
    "VolatilityBucket",
    "TrendVsRange",
    "ClosedTrade",
    "ClosedTradeHistory",
    "executed_trades",
    "AttributionDimension",
    "AttributionBucket",
    "PerformanceAttribution",
    "Ranking",
    "ExecutionQualityRecord",
    "ExecutionQualitySummary",
    "EffectivenessComparison",
    "MarketIntelligenceReview",
    "RiskReview",
    "ComplianceEffectiveness",
    "Recommendation",
    "ReportPeriod",
    "ResearchSnapshot",
]
