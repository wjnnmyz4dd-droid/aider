"""Liquidity Sweep + Market Structure Shift (ADR-026 §1, strategy 1).

Regime: REVERSAL. Requires a genuine stop hunt (a sweep that is not a
trap) followed by a Change of Character in the direction the sweep
implies -- liquidity taken from above (a swept HIGH pool) followed by a
bearish CHOCH, or from below (a swept LOW pool) followed by a bullish
CHOCH. A strategy that finds neither self-disqualifies before any
scoring runs (ADR-026 Hard Rule 3).
"""

from __future__ import annotations

from phantom.evidence_engine.models import (
    EvidenceSnapshot,
    StructureDirection,
    StructureEventType,
    SwingType,
)
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId
from ._helpers import clamp, component
from .base import Strategy

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.LIQUIDITY_SWEEP_MSS,
    purpose="Fade a stop-hunt sweep once a Change of Character confirms the reversal it implies.",
    market_regime=MarketRegime.REVERSAL,
    entry_conditions=(
        "A liquidity pool is swept (is_stop_hunt, not is_trap)",
        "A CHOCH follows in the direction the sweep implies",
    ),
    exit_conditions=("Price reaches the opposing liquidity pool or a confluence zone",),
    invalidation_conditions=("The sweep is later reclassified as a trap (is_trap) with no CHOCH follow-through",),
    preferred_sessions=(),
    preferred_pairs=(),
    required_evidence_conditions=("liquidity.sweeps non-empty", "structure.events contains a CHOCH"),
    required_market_intelligence_conditions=("pair_safety.peg_policy inactive",),
    expected_volatility="EXPANSION",
    required_support_resistance_context=("false_break_probability", "break_quality_score"),
    required_candlestick_confirmation=(),
    required_liquidity_confirmation=("Liquidity Sweeps", "Stop Hunt Detection", "Liquidity Trap Filter", "Displacement"),
)


def _choch_matches_sweep_direction(sweep_swing_type: SwingType, choch_direction: StructureDirection) -> bool:
    if sweep_swing_type == SwingType.HIGH:
        return choch_direction == StructureDirection.BEARISH
    return choch_direction == StructureDirection.BULLISH


class LiquiditySweepMssStrategy(Strategy):
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
        ineligible = check_eligibility(StrategyId.LIQUIDITY_SWEEP_MSS, pair, config)
        if ineligible is not None:
            return ineligible

        genuine_hunts = [s for s in evidence.liquidity.sweeps if s.is_stop_hunt and not s.is_trap]
        chochs = [e for e in evidence.structure.events if e.event_type == StructureEventType.CHOCH]

        matching_pairs = [
            (sweep, choch)
            for sweep in genuine_hunts
            for choch in chochs
            if _choch_matches_sweep_direction(sweep.pool.swing_type, choch.direction) and choch.confirmed_index >= sweep.sweep_index
        ]

        if not matching_pairs:
            return QualificationResult(
                strategy_id=StrategyId.LIQUIDITY_SWEEP_MSS, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="No genuine stop hunt followed by a confirming CHOCH was found",
                strengths=(), weaknesses=("no qualifying sweep+CHOCH combination",),
            )

        liquidity_component = component(evidence.report, "liquidity")
        structure_component = component(evidence.report, "structure")
        liquidity_value = liquidity_component.value if liquidity_component else 0.0
        structure_value = structure_component.value if structure_component else 0.0

        score = clamp(0.5 * liquidity_value + 0.5 * structure_value)
        trap_confidence = 1.0 - evidence.support_resistance.false_break_probability
        base_confidence = liquidity_component.confidence if liquidity_component else 0.5
        confidence = max(0.0, min(1.0, min(base_confidence, trap_confidence)))

        if confidence < config.liquidity_sweep_min_confidence or liquidity_value < config.liquidity_sweep_min_liquidity_score:
            return QualificationResult(
                strategy_id=StrategyId.LIQUIDITY_SWEEP_MSS, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Sweep+CHOCH found but confidence/liquidity score below threshold (confidence={confidence:.2f}, liquidity={liquidity_value:.1f})",
                strengths=(), weaknesses=("insufficient confidence or liquidity strength",),
            )

        best_sweep, best_choch = matching_pairs[0]
        strengths = []
        weaknesses = []
        if best_sweep.displacement_follow_through:
            strengths.append("sweep followed by genuine displacement")
        else:
            weaknesses.append("sweep lacked strong displacement follow-through")
        if evidence.support_resistance.break_quality_score >= config.strong_score_threshold:
            strengths.append(f"high break quality ({evidence.support_resistance.break_quality_score:.1f})")
        elif evidence.support_resistance.break_quality_score <= config.weak_score_threshold:
            weaknesses.append(f"low break quality ({evidence.support_resistance.break_quality_score:.1f})")

        return QualificationResult(
            strategy_id=StrategyId.LIQUIDITY_SWEEP_MSS, pair=pair, status=QualificationStatus.QUALIFIED,
            score=score, confidence=confidence,
            reason=f"Stop hunt at index {best_sweep.sweep_index} confirmed by CHOCH at index {best_choch.confirmed_index}",
            strengths=tuple(strengths), weaknesses=tuple(weaknesses),
        )


__all__ = ["LiquiditySweepMssStrategy"]
