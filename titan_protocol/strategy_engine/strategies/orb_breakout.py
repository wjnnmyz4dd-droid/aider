"""Opening Range Breakout (ORB) -- Phase 1 foundation only (ADR-035 SS17).

Establishes `StrategyId.OPENING_RANGE_BREAKOUT`'s Strategy Engine
representation and consumes `EvidenceSnapshot.opening_ranges` (ADR-035
Phase 0, `titan_protocol/evidence_engine/opening_range.py`) for
range-formed/valid gating only. No breakout-qualification rule exists
yet -- that is Phase 2's own scope (ADR-035 SS17, SS18.A item 2) -- so
`qualify()` can never return `QUALIFIED`: a formed and valid opening
range proves the underlying market fact is usable, never that a
breakout occurred, a direction exists, or a trade is warranted.
"""

from __future__ import annotations

from titan_protocol.evidence_engine.models import EvidenceSnapshot
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId
from .base import Strategy

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.OPENING_RANGE_BREAKOUT,
    purpose="Phase 1 foundation: consume the Evidence Engine's opening-range fact and gate on its formation/validity. No breakout rule exists yet (ADR-035 Phase 2).",
    market_regime=MarketRegime.BREAKOUT,
    entry_conditions=("Opening range is formed", "Opening range is valid"),
    exit_conditions=(),
    invalidation_conditions=("Opening range invalidated by a data gap or insufficient bar count",),
    preferred_sessions=(),
    preferred_pairs=(),
    required_evidence_conditions=("opening_ranges is non-empty", "opening_range.is_formed", "opening_range.is_valid"),
    required_market_intelligence_conditions=(),
    expected_volatility="N/A -- Phase 1 does not gate on volatility",
    required_support_resistance_context=(),
    required_candlestick_confirmation=(),
    required_liquidity_confirmation=(),
)


def _not_qualified(pair: str, reason: str) -> QualificationResult:
    return QualificationResult(
        strategy_id=StrategyId.OPENING_RANGE_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
        score=0.0, confidence=0.0, reason=reason, strengths=(), weaknesses=(reason,),
    )


class OrbBreakoutStrategy(Strategy):
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
        ineligible = check_eligibility(StrategyId.OPENING_RANGE_BREAKOUT, pair, config)
        if ineligible is not None:
            return ineligible

        opening_ranges = evidence.opening_ranges
        if not opening_ranges:
            return _not_qualified(pair, "No opening range configured for this evaluation cycle")
        if len(opening_ranges) > 1:
            return _not_qualified(pair, "Multiple opening ranges configured, cannot disambiguate before Phase 4")

        opening_range = opening_ranges[0]
        if not opening_range.is_formed:
            return _not_qualified(pair, "Opening range not yet formed")
        if not opening_range.is_valid:
            return _not_qualified(pair, "Opening range invalidated by a data gap or insufficient bar count")

        return _not_qualified(pair, "No breakout qualification logic exists yet -- Phase 2")


__all__ = ["OrbBreakoutStrategy"]
