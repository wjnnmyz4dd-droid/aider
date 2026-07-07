"""Statistical Risk Engine — the top-level orchestrator (`ADR-022`).

Composes every module in this package into one immutable
`StatisticalRiskAssessment`. Stateless: every call takes its historical
input explicitly (`TradeProvenanceRecord`s, `NormalizedBar`s, open
positions) and returns a fresh assessment — there is no incremental
ingestion step, unlike `knowledge.KnowledgeEngine`.

Advisory only (`ADR-022` Hard Rule 3): `statistical_recommendation` is
always the *most conservative* (most risk-reducing) of every individual
signal this engine computes — never additive, and structurally incapable
of expressing "more than 100% of the deterministic engine's approved
risk" (Hard Rule 2), because `RiskRecommendation` itself has no fifth,
risk-increasing value. `risk_decision` is accepted only as read-only
context (e.g. for a caller's own logging); nothing in this method reads
or needs its numeric fields to hold the Hard Rule 2 guarantee, which
follows from `RiskRecommendation`'s closed, reduction-only vocabulary
alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence

from ..analytics.models import TradeProvenanceRecord
from ..data_pipeline.models import NormalizedBar
from ..risk_engine.models import OpenPosition, RiskDecision
from ..scanner.models import ScannerObservation, StructureConfidence
from . import correlation, drawdown, expectancy, monte_carlo, portfolio, probability, volatility
from .config import DEFAULT_CONFIG, STATISTICAL_RISK_VERSION, StatisticalRiskConfig
from .dashboard import trend_point_from_assessment
from .models import (
    SCHEMA_VERSION,
    ConfidenceInterval,
    RiskRecommendation,
    StatisticalRiskAssessment,
    StatisticalRiskTrendReport,
)

_RECOMMENDATION_ORDER = (
    RiskRecommendation.NORMAL_RISK,
    RiskRecommendation.REDUCE_RISK_25,
    RiskRecommendation.REDUCE_RISK_50,
    RiskRecommendation.SKIP_HIGH_RISK,
)

_REGIME_CONFIDENCE_BY_STRUCTURE_CONFIDENCE: Dict[StructureConfidence, float] = {
    StructureConfidence.CLEAR: 1.0,
    StructureConfidence.AMBIGUOUS: 0.5,
    StructureConfidence.INSUFFICIENT_DATA: 0.25,
    StructureConfidence.UNKNOWN: 0.25,
}


def most_conservative(recommendations: Sequence[RiskRecommendation]) -> RiskRecommendation:
    """The single most risk-reducing recommendation among every signal —
    never a blend, never additive (`ADR-022` Hard Rule 2)."""
    if not recommendations:
        return RiskRecommendation.NORMAL_RISK
    return max(recommendations, key=_RECOMMENDATION_ORDER.index)


def value_at_risk(pnls: Sequence[float], confidence_level: float) -> Optional[float]:
    """Historical-simulation VaR: the loss magnitude at the given
    confidence level's percentile of the observed P/L distribution —
    `None` when fewer than 2 samples exist (`ADR-022` Hard Rule 7)."""
    if len(pnls) < 2:
        return None
    sorted_pnls = sorted(pnls)
    index = max(0, min(int((1.0 - confidence_level) * len(sorted_pnls)), len(sorted_pnls) - 1))
    percentile_pnl = sorted_pnls[index]
    return -percentile_pnl if percentile_pnl < 0 else 0.0


def conditional_value_at_risk(pnls: Sequence[float], confidence_level: float) -> Optional[float]:
    """Expected Shortfall: the mean loss magnitude across the tail beyond
    VaR's percentile — `None` when fewer than 2 samples exist."""
    if len(pnls) < 2:
        return None
    sorted_pnls = sorted(pnls)
    cutoff = max(1, int((1.0 - confidence_level) * len(sorted_pnls)))
    tail = sorted_pnls[:cutoff]
    mean_tail = sum(tail) / len(tail)
    return -mean_tail if mean_tail < 0 else 0.0


def kelly_criterion(pnls: Sequence[float]) -> Optional[float]:
    """Kelly Criterion fraction — advisory only, never applied
    automatically anywhere in this package or any other (`ADR-022` §1,
    capability 13). `None` when there is no honest win/loss split to
    compute it from."""
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    if not wins or not losses:
        return None
    win_rate = len(wins) / len(pnls)
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    if avg_loss <= 0:
        return None
    b = avg_win / avg_loss
    return win_rate - (1.0 - win_rate) / b


def regime_confidence_score(
    sample_size: int,
    structure_confidence: Optional[StructureConfidence],
    config: StatisticalRiskConfig = DEFAULT_CONFIG,
) -> float:
    """Regime-based statistical confidence (`ADR-022` §1, capability 19)
    — blends how much historical sample exists with how clear Scanner's
    own structural read of the current regime already is. Both
    components are already-recorded facts; neither is invented here."""
    size_component = (
        min(1.0, sample_size / config.rolling_window_trades) if config.rolling_window_trades > 0 else 0.0
    )
    regime_component = _REGIME_CONFIDENCE_BY_STRUCTURE_CONFIDENCE.get(structure_confidence, 0.25)
    return round((size_component + regime_component) / 2.0, 4)


def recommendation_for_ruin(
    risk_of_ruin: Optional[float], config: StatisticalRiskConfig = DEFAULT_CONFIG
) -> RiskRecommendation:
    if risk_of_ruin is None:
        return RiskRecommendation.REDUCE_RISK_25
    if risk_of_ruin >= config.risk_of_ruin_skip_threshold:
        return RiskRecommendation.SKIP_HIGH_RISK
    if risk_of_ruin >= config.risk_of_ruin_reduce_threshold:
        return RiskRecommendation.REDUCE_RISK_50
    return RiskRecommendation.NORMAL_RISK


class StatisticalRiskEngine:
    def __init__(self, config: StatisticalRiskConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def kelly_recommendation(self, records: Sequence[TradeProvenanceRecord]) -> Optional[float]:
        """Convenience wrapper exposing `kelly_criterion()` over the same
        rolling window `assess()` uses internally — added so callers
        (Analytics, Dashboard) can read Kelly without `assess()`'s own
        signature/return type changing (`ADR-022` Amendment 1 §A1.2 item
        2/6). Still advisory only: nothing calls this automatically."""
        return kelly_criterion(expectancy.rolling_window_pnls(records, self.config))

    def confidence_interval(
        self, trace_id: str, records: Sequence[TradeProvenanceRecord]
    ) -> ConfidenceInterval:
        """Confidence interval on expected return for `trace_id`
        (`ADR-022` §1, capability 20) — built from `expectancy.confidence_interval_bounds()`
        over the same rolling window `assess()` uses; `None` bounds mean
        an honestly too-small sample (Hard Rule 7), never a fabricated
        interval."""
        window_pnls = expectancy.rolling_window_pnls(records, self.config)
        lower, upper = expectancy.confidence_interval_bounds(window_pnls, self.config.confidence_interval_level)
        point_estimate = expectancy.rolling_expectancy(window_pnls)
        return ConfidenceInterval(
            trace_id=trace_id,
            point_estimate=point_estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=self.config.confidence_interval_level,
            sample_size=len(window_pnls),
        )

    def compute_trend(
        self, records: Sequence[TradeProvenanceRecord], now: datetime
    ) -> StatisticalRiskTrendReport:
        """Reduces every `records` entry already carrying a recorded
        `statistical_risk_assessment` (`analytics.TradeProvenanceRecord`'s
        own loosely-typed field, see that module's docstring for why) to
        one `StatisticalRiskTrendPoint`, in the order supplied — read-only,
        no new statistic computed (`ADR-022` Amendment 1 §A1.2 items 2/6)."""
        points = tuple(
            trend_point_from_assessment(
                record.statistical_risk_assessment, record.collected_at, record.kelly_recommendation
            )
            for record in records
            if record.statistical_risk_assessment is not None
        )
        return StatisticalRiskTrendReport(
            points=points, generated_at=now, statistical_risk_version=STATISTICAL_RISK_VERSION
        )

    def assess(
        self,
        trace_id: str,
        records: Sequence[TradeProvenanceRecord],
        starting_equity: float,
        open_positions: Sequence[OpenPosition] = (),
        bars: Sequence[NormalizedBar] = (),
        scanner_observation: Optional[ScannerObservation] = None,
        risk_decision: Optional[RiskDecision] = None,
    ) -> StatisticalRiskAssessment:
        del risk_decision  # read-only context only; see module docstring

        window_pnls = expectancy.rolling_window_pnls(records, self.config)
        sample_size = len(window_pnls)
        has_min_sample = sample_size >= self.config.min_sample_size

        seed = monte_carlo.derive_seed(trace_id, self.config)
        mc_result = (
            monte_carlo.simulate(
                window_pnls, starting_equity, self.config.monte_carlo_ruin_threshold_pct, seed, self.config
            )
            if has_min_sample and starting_equity > 0
            else None
        )

        risk_of_ruin_value = mc_result.probability_of_ruin if mc_result is not None else None
        probability_of_drawdown_value = (
            probability.probability_of_reaching_total_drawdown_limit(
                window_pnls, starting_equity, seed, self.config
            )
            if has_min_sample and starting_equity > 0
            else None
        )
        expected_drawdown_value = drawdown.expected_drawdown(mc_result)
        expected_return_value = (
            (mc_result.mean_final_equity - starting_equity) if mc_result is not None else None
        )

        volatility_state = volatility.build_volatility_state(bars, self.config)
        correlation_state = correlation.build_correlation_state(open_positions, self.config)
        heat = portfolio.portfolio_heat(open_positions)
        currency_exposure_map = portfolio.currency_exposure(open_positions)

        structure_confidence = (
            scanner_observation.structure_confidence if scanner_observation is not None else None
        )

        recommendations: List[RiskRecommendation] = [
            volatility.recommendation_for_volatility(volatility_state),
            correlation.recommendation_for_correlation(correlation_state),
            portfolio.recommendation_for_portfolio_heat(heat, self.config),
            portfolio.recommendation_for_currency_exposure(currency_exposure_map, self.config),
            recommendation_for_ruin(risk_of_ruin_value, self.config),
        ]
        if not has_min_sample:
            recommendations.append(RiskRecommendation.REDUCE_RISK_25)

        return StatisticalRiskAssessment(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            confidence_score=regime_confidence_score(sample_size, structure_confidence, self.config),
            risk_of_ruin=risk_of_ruin_value,
            probability_of_drawdown=probability_of_drawdown_value,
            expected_drawdown=expected_drawdown_value,
            expected_return=expected_return_value,
            rolling_expectancy=expectancy.rolling_expectancy(window_pnls) if has_min_sample else None,
            rolling_profit_factor=expectancy.rolling_profit_factor(window_pnls) if has_min_sample else None,
            rolling_win_rate=expectancy.rolling_win_rate(window_pnls) if has_min_sample else None,
            sharpe_ratio=expectancy.rolling_sharpe_ratio(window_pnls) if has_min_sample else None,
            sortino_ratio=expectancy.rolling_sortino_ratio(window_pnls) if has_min_sample else None,
            value_at_risk=(
                value_at_risk(window_pnls, self.config.var_confidence_level) if has_min_sample else None
            ),
            conditional_value_at_risk=(
                conditional_value_at_risk(window_pnls, self.config.cvar_confidence_level)
                if has_min_sample
                else None
            ),
            portfolio_heat=heat,
            volatility_state=volatility_state,
            correlation_state=correlation_state,
            statistical_recommendation=most_conservative(recommendations),
        )


__all__ = [
    "StatisticalRiskEngine",
    "most_conservative",
    "value_at_risk",
    "conditional_value_at_risk",
    "kelly_criterion",
    "regime_confidence_score",
    "recommendation_for_ruin",
]
