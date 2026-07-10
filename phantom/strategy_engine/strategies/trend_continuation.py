"""Trend Continuation (ADR-026 §1, strategy 3).

Regime: TRENDING. Requires the raw structural trend (higher-highs/
higher-lows or lower-highs/lower-lows, per Evidence Engine's swing
sequence) to already be directional -- this strategy never trades a
market Evidence Engine itself classifies as RANGE/COMPRESSION/EXPANSION/
REVERSAL.
"""

from __future__ import annotations

from phantom.evidence_engine.models import EvidenceSnapshot, TrendClassification
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId
from ._helpers import clamp, component
from .base import Strategy

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.TREND_CONTINUATION,
    purpose="Join an already-established directional trend on a confirming pullback.",
    market_regime=MarketRegime.TRENDING,
    entry_conditions=("structure.trend is TRENDING_UP or TRENDING_DOWN", "trend component score above threshold"),
    exit_conditions=("structure.trend reverts to RANGE, COMPRESSION, or REVERSAL",),
    invalidation_conditions=("A CHOCH against the established trend direction is confirmed",),
    preferred_sessions=(),
    preferred_pairs=(),
    required_evidence_conditions=("structure.trend directional", "trend component score"),
    required_market_intelligence_conditions=("pair_safety.peg_policy inactive",),
    expected_volatility="MODERATE_TO_EXPANSION",
    required_support_resistance_context=("confluence_zones",),
    required_candlestick_confirmation=(),
    required_liquidity_confirmation=(),
)

_DIRECTIONAL = (TrendClassification.TRENDING_UP, TrendClassification.TRENDING_DOWN)


class TrendContinuationStrategy(Strategy):
    @property
    def definition(self) -> StrategyDefinition:
        return _DEFINITION

    def qualify(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        config: StrategyEngineConfig,
    ) -> QualificationResult:
        ineligible = check_eligibility(StrategyId.TREND_CONTINUATION, pair, config)
        if ineligible is not None:
            return ineligible

        if evidence.structure.trend not in _DIRECTIONAL:
            return QualificationResult(
                strategy_id=StrategyId.TREND_CONTINUATION, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Structural trend is {evidence.structure.trend.value}, not directional",
                strengths=(), weaknesses=("market is not in a directional trend",),
            )

        trend_component = component(evidence.report, "trend")
        trend_value = trend_component.value if trend_component else 0.0
        if trend_value < config.trend_continuation_min_trend_score:
            return QualificationResult(
                strategy_id=StrategyId.TREND_CONTINUATION, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Trend score {trend_value:.1f} below threshold {config.trend_continuation_min_trend_score}",
                strengths=(), weaknesses=("trend score too weak",),
            )

        volatility_value = evidence.volatility.volatility_score
        score = clamp(0.7 * trend_value + 0.3 * volatility_value)
        confidence = trend_component.confidence if trend_component else 0.5

        strengths = [f"directional trend confirmed ({evidence.structure.trend.value})"]
        weaknesses = []
        if evidence.volatility.is_compression:
            weaknesses.append("volatility is compressing, continuation may stall")
        elif evidence.volatility.is_expansion:
            strengths.append("volatility expanding, supports continuation")

        return QualificationResult(
            strategy_id=StrategyId.TREND_CONTINUATION, pair=pair, status=QualificationStatus.QUALIFIED,
            score=score, confidence=confidence,
            reason=f"Structural trend {evidence.structure.trend.value} with trend score {trend_value:.1f}",
            strengths=tuple(strengths), weaknesses=tuple(weaknesses),
        )


__all__ = ["TrendContinuationStrategy"]
