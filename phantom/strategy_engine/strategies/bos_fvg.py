"""BOS + Fair Value Gap (ADR-026 §1, strategy 2).

Regime: TRENDING. Requires a confirmed Break of Structure (internal or
external) with at least one still-unfilled Fair Value Gap in the same
direction -- an unfilled gap in the direction of the break is the
entry-continuation signal this strategy targets.
"""

from __future__ import annotations

from phantom.evidence_engine.models import EvidenceSnapshot, StructureDirection
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId
from ._helpers import clamp, component
from .base import Strategy

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.BOS_FVG,
    purpose="Enter a confirmed structural break while an unfilled Fair Value Gap in the same direction remains as a continuation target.",
    market_regime=MarketRegime.TRENDING,
    entry_conditions=("A BOS (internal or external) is confirmed", "An unfilled FVG exists in the same direction"),
    exit_conditions=("The Fair Value Gap fills, or the next structural level is reached",),
    invalidation_conditions=("The Fair Value Gap fills before any continuation follow-through",),
    preferred_sessions=(),
    preferred_pairs=(),
    required_evidence_conditions=("structure.events contains a BOS", "fair_value_gaps contains an unfilled matching-direction gap"),
    required_market_intelligence_conditions=("pair_safety.peg_policy inactive",),
    expected_volatility="EXPANSION",
    required_support_resistance_context=("break_quality_score",),
    required_candlestick_confirmation=(),
    required_liquidity_confirmation=(),
)

_BOS_TYPES = {"BOS_INTERNAL", "BOS_EXTERNAL"}


class BosFvgStrategy(Strategy):
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
        ineligible = check_eligibility(StrategyId.BOS_FVG, pair, config)
        if ineligible is not None:
            return ineligible

        bos_events = [e for e in evidence.structure.events if e.event_type.value in _BOS_TYPES]
        unfilled_gaps = [g for g in evidence.fair_value_gaps if not g.filled]

        matching = [
            (bos, gap)
            for bos in bos_events
            for gap in unfilled_gaps
            if bos.direction == gap.direction and gap.end_index <= bos.confirmed_index
        ]

        if not matching:
            return QualificationResult(
                strategy_id=StrategyId.BOS_FVG, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="No confirmed BOS with a matching unfilled Fair Value Gap was found",
                strengths=(), weaknesses=("no qualifying BOS+FVG combination",),
            )

        structure_component = component(evidence.report, "structure")
        structure_value = structure_component.value if structure_component else 0.0

        if structure_value < config.bos_fvg_min_structure_score:
            return QualificationResult(
                strategy_id=StrategyId.BOS_FVG, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"BOS+FVG found but structure score below threshold ({structure_value:.1f})",
                strengths=(), weaknesses=("insufficient structural strength",),
            )

        score = clamp(0.6 * structure_value + 0.4 * evidence.support_resistance.break_quality_score)
        confidence = structure_component.confidence if structure_component else 0.5
        if confidence < config.bos_fvg_min_confidence:
            return QualificationResult(
                strategy_id=StrategyId.BOS_FVG, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"BOS+FVG found but confidence below threshold ({confidence:.2f})",
                strengths=(), weaknesses=("insufficient confidence",),
            )

        best_bos, best_gap = matching[0]
        strengths = []
        weaknesses = []
        if evidence.support_resistance.break_quality_score >= config.strong_score_threshold:
            strengths.append(f"high break quality ({evidence.support_resistance.break_quality_score:.1f})")
        else:
            weaknesses.append(f"break quality only {evidence.support_resistance.break_quality_score:.1f}")
        gap_width_pct = abs(best_gap.gap_high - best_gap.gap_low) / best_gap.gap_low * 100.0 if best_gap.gap_low else 0.0
        strengths.append(f"unfilled {best_gap.direction.value.lower()} FVG ({gap_width_pct:.3f}% wide)")

        return QualificationResult(
            strategy_id=StrategyId.BOS_FVG, pair=pair, status=QualificationStatus.QUALIFIED,
            score=score, confidence=confidence,
            reason=f"BOS at index {best_bos.confirmed_index} with unfilled FVG [{best_gap.start_index}-{best_gap.end_index}]",
            strengths=tuple(strengths), weaknesses=tuple(weaknesses),
        )


__all__ = ["BosFvgStrategy"]
