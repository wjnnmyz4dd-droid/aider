"""Range Reversal (ADR-026 §1, strategy 5).

Regime: RANGING. Requires a genuinely non-trending market (raw
structural trend is RANGE), a nearby confluence zone (Evidence
Engine's `confluence_zones` are already sorted nearest-to-current-price
first, so `[0]` is the relevant one), and a confirming candlestick
reversal pattern.
"""

from __future__ import annotations

from phantom.evidence_engine.models import EvidenceSnapshot, TrendClassification
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId, TradeIntent
from ._helpers import clamp, component
from .base import Strategy


def _trade_intent_for_zone(nearest_zone, evidence: EvidenceSnapshot) -> TradeIntent:
    """(ADR-026 Amendment 1) A bounce off support is a `BUY`; a
    rejection at resistance is a `SELL`. `sources` already carries the
    literal `"support"`/`"resistance"` label whenever a structural
    support/resistance level contributed to this zone
    (`support_resistance.py`'s own `sourced_prices` construction) --
    reused here, never recomputed. If neither label is present (the
    zone was built purely from session/psychological levels), fall
    back to comparing the zone's price against the session range's
    midpoint -- both already on `SupportResistanceContext`."""

    if "support" in nearest_zone.sources:
        return TradeIntent.BUY
    if "resistance" in nearest_zone.sources:
        return TradeIntent.SELL
    midpoint = (evidence.support_resistance.session_high + evidence.support_resistance.session_low) / 2.0
    return TradeIntent.BUY if nearest_zone.price <= midpoint else TradeIntent.SELL

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.RANGE_REVERSAL,
    purpose="Fade the edge of a confirmed range at a confluence zone, backed by a reversal candlestick pattern.",
    market_regime=MarketRegime.RANGING,
    entry_conditions=("structure.trend is RANGE", "a confluence zone exists nearby", "a candlestick pattern confirms"),
    exit_conditions=("Price reaches the opposite side of the range",),
    invalidation_conditions=("structure.trend becomes directional (a genuine breakout)",),
    preferred_sessions=(),
    preferred_pairs=(),
    required_evidence_conditions=("structure.trend is RANGE", "confluence_zones non-empty", "candlestick confirmation"),
    required_market_intelligence_conditions=("pair_safety.peg_policy inactive",),
    expected_volatility="COMPRESSION_TO_MODERATE",
    required_support_resistance_context=("confluence_zones", "confluence_score"),
    required_candlestick_confirmation=("single-candle", "two-candle", "three-candle reversal patterns"),
    required_liquidity_confirmation=(),
)


class RangeReversalStrategy(Strategy):
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
        ineligible = check_eligibility(StrategyId.RANGE_REVERSAL, pair, config)
        if ineligible is not None:
            return ineligible

        if evidence.structure.trend != TrendClassification.RANGE:
            return QualificationResult(
                strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Structural trend is {evidence.structure.trend.value}, not RANGE",
                strengths=(), weaknesses=("market is not ranging",),
            )

        if not evidence.support_resistance.confluence_zones:
            return QualificationResult(
                strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="No confluence zone available to anchor a range reversal",
                strengths=(), weaknesses=("no confluence zones",),
            )

        if not evidence.candlesticks:
            return QualificationResult(
                strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="No candlestick confirmation available",
                strengths=(), weaknesses=("no candlestick pattern observed",),
            )

        best_candlestick = max(evidence.candlesticks, key=lambda c: c.confidence)
        if best_candlestick.confidence < config.range_reversal_min_candlestick_confidence:
            return QualificationResult(
                strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Strongest candlestick confidence {best_candlestick.confidence:.2f} below threshold",
                strengths=(), weaknesses=("candlestick confirmation too weak",),
            )

        nearest_zone = evidence.support_resistance.confluence_zones[0]
        if nearest_zone.confluence_score < config.range_reversal_min_confluence_score:
            return QualificationResult(
                strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Nearest confluence zone score {nearest_zone.confluence_score:.1f} below threshold",
                strengths=(), weaknesses=("confluence too weak",),
            )

        trend_component = component(evidence.report, "trend")
        trend_value = trend_component.value if trend_component else 0.0
        if trend_value > config.range_reversal_max_trend_score:
            return QualificationResult(
                strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Trend score {trend_value:.1f} too high for a range read",
                strengths=(), weaknesses=("trend score inconsistent with ranging market",),
            )

        score = clamp(0.5 * nearest_zone.confluence_score + 0.5 * (best_candlestick.confidence * 100.0))
        confidence = min(best_candlestick.confidence, nearest_zone.confluence_score / 100.0)

        strengths = [
            f"confluence zone with {len(nearest_zone.sources)} agreeing source(s)",
            f"{best_candlestick.pattern.value} confirmation (confidence={best_candlestick.confidence:.2f})",
        ]
        weaknesses = []
        if evidence.support_resistance.false_break_probability >= 0.5:
            weaknesses.append(f"elevated false-break probability ({evidence.support_resistance.false_break_probability:.2f})")

        return QualificationResult(
            strategy_id=StrategyId.RANGE_REVERSAL, pair=pair, status=QualificationStatus.QUALIFIED,
            score=score, confidence=confidence,
            reason=f"Range reversal setup at confluence zone (price={nearest_zone.price:.5f}, score={nearest_zone.confluence_score:.1f})",
            strengths=tuple(strengths), weaknesses=tuple(weaknesses),
            trade_intent=_trade_intent_for_zone(nearest_zone, evidence),
        )


__all__ = ["RangeReversalStrategy"]
