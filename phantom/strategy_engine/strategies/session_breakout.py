"""Session Breakout (ADR-026 §1, strategy 4).

Regime: BREAKOUT. Per the task's own "Additional Requirements": prefer
London and the London/New York Overlap, then Early New York. Requires
volatility expansion -- a breakout with no expansion is not a breakout.
"""

from __future__ import annotations

from typing import Optional

from phantom.evidence_engine.models import EvidenceSnapshot, SessionName, TrendClassification
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..eligibility import check_eligibility
from ..models import MarketRegime, QualificationResult, QualificationStatus, StrategyDefinition, StrategyId, TradeIntent
from ._helpers import clamp, component, trade_intent_from_structure_direction
from .base import Strategy

_PREFERRED_SESSIONS = (SessionName.LONDON, SessionName.LONDON_NEW_YORK_OVERLAP, SessionName.EARLY_NEW_YORK)

_TRADE_INTENT_BY_TREND = {
    TrendClassification.TRENDING_UP: TradeIntent.BUY,
    TrendClassification.TRENDING_DOWN: TradeIntent.SELL,
}


def _breakout_trade_intent(evidence: EvidenceSnapshot) -> Optional[TradeIntent]:
    """(ADR-026 Amendment 1) The most recently confirmed structural
    break already implies the breakout's direction; if none exists,
    fall back to an already-directional raw trend. Returns `None` --
    never a guess -- if no directional fact is available at all."""

    if evidence.structure.events:
        latest_event = max(evidence.structure.events, key=lambda e: e.confirmed_index)
        return trade_intent_from_structure_direction(latest_event.direction)
    return _TRADE_INTENT_BY_TREND.get(evidence.structure.trend)

_DEFINITION = StrategyDefinition(
    strategy_id=StrategyId.SESSION_BREAKOUT,
    purpose="Trade a volatility-expansion breakout during London, the London/New York overlap, or Early New York.",
    market_regime=MarketRegime.BREAKOUT,
    entry_conditions=("Current session is London, the Overlap, or Early New York", "Volatility is expanding"),
    exit_conditions=("Volatility reverts to compression", "Session ends"),
    invalidation_conditions=("The breakout reverses back inside the pre-breakout range",),
    preferred_sessions=_PREFERRED_SESSIONS,
    preferred_pairs=(),
    required_evidence_conditions=("session.session in preferred set", "volatility.is_expansion"),
    required_market_intelligence_conditions=("pair_safety.session.preferred", "pair_safety.news.blackout_active is False"),
    expected_volatility="EXPANSION",
    required_support_resistance_context=("session_high", "session_low"),
    required_candlestick_confirmation=(),
    required_liquidity_confirmation=("Displacement",),
)


class SessionBreakoutStrategy(Strategy):
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
        ineligible = check_eligibility(StrategyId.SESSION_BREAKOUT, pair, config)
        if ineligible is not None:
            return ineligible

        if evidence.session.session not in _PREFERRED_SESSIONS:
            return QualificationResult(
                strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Session {evidence.session.session.value} is not London/Overlap/Early New York",
                strengths=(), weaknesses=("outside preferred session window",),
            )

        if not evidence.volatility.is_expansion:
            return QualificationResult(
                strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="Volatility is not expanding -- no breakout to trade",
                strengths=(), weaknesses=("no volatility expansion observed",),
            )

        if market_intelligence.pair_safety.news.blackout_active:
            return QualificationResult(
                strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="News blackout active -- avoid high impact news per Additional Requirements",
                strengths=(), weaknesses=("news blackout active",),
            )

        session_component = component(evidence.report, "session")
        session_value = session_component.value if session_component else 0.0
        mi_session_score = market_intelligence.pair_safety.session.session_score

        if session_value < config.session_breakout_min_session_score:
            return QualificationResult(
                strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Session score {session_value:.1f} below threshold {config.session_breakout_min_session_score}",
                strengths=(), weaknesses=("session quality too low",),
            )

        if evidence.volatility.volatility_score < config.session_breakout_min_volatility_score:
            return QualificationResult(
                strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason=f"Volatility score {evidence.volatility.volatility_score:.1f} below threshold",
                strengths=(), weaknesses=("volatility score too low despite expansion flag",),
            )

        trade_intent = _breakout_trade_intent(evidence)
        if trade_intent is None:
            return QualificationResult(
                strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.NOT_QUALIFIED,
                score=0.0, confidence=0.0,
                reason="No directional fact available (no structure events and trend not directional) -- fail closed, never guessed",
                strengths=(), weaknesses=("no structural break or directional trend to derive a breakout direction from",),
            )

        score = clamp(0.4 * session_value + 0.3 * mi_session_score + 0.3 * evidence.volatility.volatility_score)
        confidence = session_component.confidence if session_component else 0.5

        strengths = [f"preferred session ({evidence.session.session.value})", "volatility expanding"]
        weaknesses = []
        if not market_intelligence.pair_safety.session.preferred:
            weaknesses.append("Market Intelligence does not flag this session as preferred")

        return QualificationResult(
            strategy_id=StrategyId.SESSION_BREAKOUT, pair=pair, status=QualificationStatus.QUALIFIED,
            score=score, confidence=confidence,
            reason=f"Volatility expansion during {evidence.session.session.value}",
            strengths=tuple(strengths), weaknesses=tuple(weaknesses),
            trade_intent=trade_intent,
        )


__all__ = ["SessionBreakoutStrategy"]
