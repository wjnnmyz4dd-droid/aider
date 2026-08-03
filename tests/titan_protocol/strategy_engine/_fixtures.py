"""Shared test-only fixtures for the Strategy Engine test suite --
hand-constructs `EvidenceSnapshot`/`MarketIntelligenceSnapshot` objects
directly (rather than deriving them from synthetic bars, which is
fragile for hitting exact QUALIFIED paths) so each strategy's
qualification logic can be tested precisely."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from titan_protocol.evidence_engine.models import (
    CandlestickMatch,
    CandlestickPattern,
    ComponentScore,
    ConfluenceZone,
    EvidenceReport,
    EvidenceScore,
    EvidenceSnapshot,
    FairValueGap,
    LiquidityPool,
    LiquidityResult,
    LiquiditySweep,
    MarketStructureResult,
    PatternContext,
    SessionName,
    SessionState,
    StructureDirection,
    StructureEvent,
    StructureEventType,
    SupportResistanceContext,
    SwingPoint,
    SwingType,
    TrendClassification,
    VolatilityState,
)
from titan_protocol.market_intelligence.models import (
    LiquidityIntelligence,
    MarketIntelligenceExplanation,
    MarketIntelligenceSnapshot,
    MarketSafetyStatus,
    PairNewsIntelligence,
    PairSafety,
    PegPolicyStatus,
    SessionIntelligence,
    TradeReadiness,
)
from titan_protocol.strategy_engine.config import StrategyEngineConfig

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap

_COMPONENT_NAMES = ("structure", "liquidity", "candlestick", "trend", "volatility", "session", "indicator")


def make_config(**overrides) -> StrategyEngineConfig:
    return StrategyEngineConfig(**overrides)


def make_component(name: str, value: float = 50.0, weight: float = 0.15, confidence: float = 0.7, reason: str = "test") -> ComponentScore:
    return ComponentScore(name=name, value=value, weight=weight, confidence=confidence, reason=reason)


def make_evidence_report(
    symbol: str = "EURUSD",
    now: datetime = T0,
    component_overrides: Optional[dict] = None,
) -> EvidenceReport:
    overrides = component_overrides or {}
    components = tuple(make_component(name, **overrides.get(name, {})) for name in _COMPONENT_NAMES)
    composite = sum(c.value * c.weight for c in components)
    score = EvidenceScore(composite=composite, components=components)
    return EvidenceReport(
        symbol=symbol, generated_at=now, score=score,
        strengths=(), weaknesses=(), confidence_explanation="test",
    )


def make_structure_result(
    trend: TrendClassification = TrendClassification.RANGE,
    events: Tuple[StructureEvent, ...] = (),
    swings: Tuple[SwingPoint, ...] = (),
    support_levels: Tuple = (),
    resistance_levels: Tuple = (),
) -> MarketStructureResult:
    return MarketStructureResult(
        swings=swings, events=events, trend=trend,
        support_levels=support_levels, resistance_levels=resistance_levels,
    )


def make_liquidity_result(pools: Tuple[LiquidityPool, ...] = (), sweeps: Tuple[LiquiditySweep, ...] = ()) -> LiquidityResult:
    return LiquidityResult(pools=pools, sweeps=sweeps)


def make_volatility_state(atr: float = 0.001, is_expansion: bool = False, is_compression: bool = False, volatility_score: float = 50.0) -> VolatilityState:
    return VolatilityState(atr=atr, is_expansion=is_expansion, is_compression=is_compression, volatility_score=volatility_score)


def make_session_state(session: SessionName = SessionName.LONDON_NEW_YORK_OVERLAP, quality_score: float = 100.0) -> SessionState:
    return SessionState(session=session, quality_score=quality_score)


def make_support_resistance_context(
    confluence_zones: Tuple[ConfluenceZone, ...] = (),
    break_quality_score: float = 50.0,
    false_break_probability: float = 0.3,
    session_high: float = 1.11,
    session_low: float = 1.09,
) -> SupportResistanceContext:
    return SupportResistanceContext(
        previous_day_high=None, previous_day_low=None,
        previous_week_high=None, previous_week_low=None,
        previous_month_high=None, previous_month_low=None,
        session_high=session_high, session_low=session_low,
        psychological_levels=(), confluence_zones=confluence_zones,
        break_quality_score=break_quality_score, false_break_probability=false_break_probability,
    )


def make_evidence_snapshot(
    symbol: str = "EURUSD",
    now: datetime = T0,
    component_overrides: Optional[dict] = None,
    structure: Optional[MarketStructureResult] = None,
    liquidity: Optional[LiquidityResult] = None,
    candlesticks: Tuple[CandlestickMatch, ...] = (),
    volatility: Optional[VolatilityState] = None,
    session: Optional[SessionState] = None,
    support_resistance: Optional[SupportResistanceContext] = None,
    fair_value_gaps: Tuple[FairValueGap, ...] = (),
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        report=make_evidence_report(symbol, now, component_overrides),
        structure=structure or make_structure_result(),
        liquidity=liquidity or make_liquidity_result(),
        candlesticks=candlesticks,
        volatility=volatility or make_volatility_state(),
        session=session or make_session_state(),
        support_resistance=support_resistance or make_support_resistance_context(),
        fair_value_gaps=fair_value_gaps,
    )


def make_pair_news_intelligence(pair: str = "EURUSD", news_score: float = 100.0, blackout_active: bool = False, blackout_reason: Optional[str] = None) -> PairNewsIntelligence:
    return PairNewsIntelligence(
        pair=pair, upcoming_events=(), active_events=(), recent_events=(),
        news_score=news_score, blackout_active=blackout_active, blackout_reason=blackout_reason,
    )


def make_liquidity_intelligence(liquidity_score: float = 100.0, current_spread: float = 1.0, average_spread: float = 1.0) -> LiquidityIntelligence:
    return LiquidityIntelligence(current_spread=current_spread, average_spread=average_spread, spread_widening=False, liquidity_score=liquidity_score, reason="test")


def make_session_intelligence(session: SessionName = SessionName.LONDON_NEW_YORK_OVERLAP, session_score: float = 100.0, preferred: bool = True) -> SessionIntelligence:
    return SessionIntelligence(session=session, session_score=session_score, preferred=preferred, reason="test")


def make_market_safety_status(safety_score: float = 100.0, closed: bool = False, halted: bool = False, maintenance: bool = False, holiday: bool = False) -> MarketSafetyStatus:
    return MarketSafetyStatus(
        is_holiday=holiday, is_early_close=False, is_weekend_approaching=False,
        broker_maintenance=maintenance, trading_halted=halted, market_closed=closed,
        safety_score=safety_score, reason="test",
    )


def make_peg_policy_status(active: bool = False) -> PegPolicyStatus:
    return PegPolicyStatus(active=active, event_type=None, reason="test" if active else None)


def make_pair_safety(
    pair: str = "EURUSD",
    news: Optional[PairNewsIntelligence] = None,
    liquidity: Optional[LiquidityIntelligence] = None,
    session: Optional[SessionIntelligence] = None,
    market_safety: Optional[MarketSafetyStatus] = None,
    peg_policy: Optional[PegPolicyStatus] = None,
    pair_safety_score: float = 100.0,
) -> PairSafety:
    return PairSafety(
        pair=pair,
        news=news or make_pair_news_intelligence(pair),
        liquidity=liquidity or make_liquidity_intelligence(),
        session=session or make_session_intelligence(),
        market_safety=market_safety or make_market_safety_status(),
        peg_policy=peg_policy or make_peg_policy_status(),
        pair_safety_score=pair_safety_score,
    )


def make_trade_readiness(pair: str = "EURUSD", readiness_score: float = 100.0, reasons: Tuple[str, ...] = ()) -> TradeReadiness:
    return TradeReadiness(pair=pair, readiness_score=readiness_score, reasons=reasons)


def make_mi_snapshot(
    pair: str = "EURUSD",
    now: datetime = T0,
    pair_safety: Optional[PairSafety] = None,
    trade_readiness: Optional[TradeReadiness] = None,
) -> MarketIntelligenceSnapshot:
    ps = pair_safety or make_pair_safety(pair)
    tr = trade_readiness or make_trade_readiness(pair)
    explanation = MarketIntelligenceExplanation(
        why_score_changed="test", upcoming_events=(), current_restrictions=(),
        blackout_reason=None, session_reason="test", liquidity_reason="test",
        trade_readiness_explanation="test",
    )
    return MarketIntelligenceSnapshot(pair=pair, generated_at=now, pair_safety=ps, trade_readiness=tr, explanation=explanation)
