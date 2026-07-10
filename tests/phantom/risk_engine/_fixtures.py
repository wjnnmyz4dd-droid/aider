"""Shared test-only fixtures for the Risk Engine test suite --
hand-constructs `EvidenceSnapshot`/`MarketIntelligenceSnapshot`/
`StrategySnapshot` directly, same rationale as the Strategy Engine's own
`_fixtures.py`: precise QUALIFIED/APPROVED paths are far more reliable
to construct by hand than to coax out of synthetic data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from phantom.evidence_engine.models import (
    ComponentScore,
    EvidenceReport,
    EvidenceScore,
    EvidenceSnapshot,
    LiquidityResult,
    MarketStructureResult,
    SessionName,
    SessionState,
    SupportResistanceContext,
    TrendClassification,
    VolatilityState,
)
from phantom.market_intelligence.models import (
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
from phantom.risk_engine.config import RiskEngineConfig
from phantom.risk_engine.models import Direction, OpenPosition, PortfolioState, TradeHistory, TradeResult
from phantom.strategy_engine.models import (
    QualificationResult,
    QualificationStatus,
    StrategyId,
    StrategySnapshot,
    WinningStrategy,
)

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap

_COMPONENT_NAMES = ("structure", "liquidity", "candlestick", "trend", "volatility", "session", "indicator")


def make_config(**overrides) -> RiskEngineConfig:
    return RiskEngineConfig(**overrides)


def make_evidence_snapshot(
    symbol: str = "EURUSD",
    now: datetime = T0,
    evidence_score: float = 90.0,
    volatility: Optional[VolatilityState] = None,
) -> EvidenceSnapshot:
    components = tuple(
        ComponentScore(name=name, value=evidence_score, weight=1.0 / len(_COMPONENT_NAMES), confidence=0.8, reason="test")
        for name in _COMPONENT_NAMES
    )
    score = EvidenceScore(composite=evidence_score, components=components)
    report = EvidenceReport(symbol=symbol, generated_at=now, score=score, strengths=(), weaknesses=(), confidence_explanation="test")
    return EvidenceSnapshot(
        report=report,
        structure=MarketStructureResult(swings=(), events=(), trend=TrendClassification.RANGE, support_levels=(), resistance_levels=()),
        liquidity=LiquidityResult(pools=(), sweeps=()),
        candlesticks=(),
        volatility=volatility or VolatilityState(atr=0.001, is_expansion=False, is_compression=False, volatility_score=50.0),
        session=SessionState(session=SessionName.LONDON_NEW_YORK_OVERLAP, quality_score=100.0),
        support_resistance=SupportResistanceContext(
            previous_day_high=None, previous_day_low=None, previous_week_high=None, previous_week_low=None,
            previous_month_high=None, previous_month_low=None, session_high=1.11, session_low=1.09,
            psychological_levels=(), confluence_zones=(), break_quality_score=50.0, false_break_probability=0.3,
        ),
        fair_value_gaps=(),
    )


def make_mi_snapshot(
    pair: str = "EURUSD",
    now: datetime = T0,
    liquidity_score: float = 100.0,
) -> MarketIntelligenceSnapshot:
    pair_safety = PairSafety(
        pair=pair,
        news=PairNewsIntelligence(pair=pair, upcoming_events=(), active_events=(), recent_events=(), news_score=100.0, blackout_active=False, blackout_reason=None),
        liquidity=LiquidityIntelligence(current_spread=1.0, average_spread=1.0, spread_widening=False, liquidity_score=liquidity_score, reason="test"),
        session=SessionIntelligence(session=SessionName.LONDON_NEW_YORK_OVERLAP, session_score=100.0, preferred=True, reason="test"),
        market_safety=MarketSafetyStatus(
            is_holiday=False, is_early_close=False, is_weekend_approaching=False,
            broker_maintenance=False, trading_halted=False, market_closed=False, safety_score=100.0, reason="test",
        ),
        peg_policy=PegPolicyStatus(active=False, event_type=None, reason=None),
        pair_safety_score=100.0,
    )
    trade_readiness = TradeReadiness(pair=pair, readiness_score=100.0, reasons=())
    explanation = MarketIntelligenceExplanation(
        why_score_changed="test", upcoming_events=(), current_restrictions=(),
        blackout_reason=None, session_reason="test", liquidity_reason="test", trade_readiness_explanation="test",
    )
    return MarketIntelligenceSnapshot(pair=pair, generated_at=now, pair_safety=pair_safety, trade_readiness=trade_readiness, explanation=explanation)


def make_strategy_snapshot(
    pair: str = "EURUSD",
    now: datetime = T0,
    rejected: bool = False,
    strategy_id: StrategyId = StrategyId.TREND_CONTINUATION,
    score: float = 80.0,
    confidence: float = 0.8,
) -> StrategySnapshot:
    if rejected:
        return StrategySnapshot(
            pair=pair, generated_at=now, winning_strategy=None, all_qualifications=(),
            rejected=True, rejection_reason="no strategy qualified",
            supporting_evidence_summary="test", supporting_market_intelligence_summary="test",
        )
    qualification = QualificationResult(
        strategy_id=strategy_id, pair=pair, status=QualificationStatus.QUALIFIED,
        score=score, confidence=confidence, reason="test", strengths=("strong trend",), weaknesses=(),
    )
    winning = WinningStrategy(strategy_id=strategy_id, qualification=qualification)
    return StrategySnapshot(
        pair=pair, generated_at=now, winning_strategy=winning, all_qualifications=(qualification,),
        rejected=False, rejection_reason=None,
        supporting_evidence_summary="test", supporting_market_intelligence_summary="test",
    )


def make_trade_result(
    pair: str = "EURUSD",
    strategy_id: Optional[StrategyId] = StrategyId.TREND_CONTINUATION,
    risk_r: float = 1.0,
    r_multiple: float = 1.0,
    opened_at: datetime = T0,
    closed_at: datetime = T0,
    won: Optional[bool] = None,
) -> TradeResult:
    return TradeResult(
        pair=pair, strategy_id=strategy_id, risk_r=risk_r, r_multiple=r_multiple,
        opened_at=opened_at, closed_at=closed_at, won=won if won is not None else r_multiple > 0,
    )


def make_trade_history(results: Sequence[TradeResult] = ()) -> TradeHistory:
    return TradeHistory(results=tuple(results))


def make_repeating_trade_history(
    pair: str = "EURUSD",
    count: int = 30,
    win_r: float = 2.0,
    loss_r: float = -1.0,
    win_rate: float = 0.5,
    start: datetime = T0 - timedelta(days=60),
    spacing: timedelta = timedelta(days=1),
    strategy_id: Optional[StrategyId] = StrategyId.TREND_CONTINUATION,
) -> TradeHistory:
    """A deterministic alternating-outcome trade history: exactly
    `round(count * win_rate)` wins, spaced one per day, oldest first."""

    num_wins = round(count * win_rate)
    results = []
    for i in range(count):
        r_multiple = win_r if i % 2 == 0 and (i // 2) < num_wins else loss_r
        opened = start + spacing * i
        results.append(make_trade_result(
            pair=pair, strategy_id=strategy_id, risk_r=1.0, r_multiple=r_multiple,
            opened_at=opened, closed_at=opened + timedelta(hours=4), won=r_multiple > 0,
        ))
    return make_trade_history(results)


def make_open_position(
    pair: str = "GBPUSD",
    direction: Direction = Direction.LONG,
    size_r: float = 1.0,
    opened_at: datetime = T0,
) -> OpenPosition:
    return OpenPosition(pair=pair, direction=direction, size_r=size_r, opened_at=opened_at)


def make_portfolio_state(positions: Sequence[OpenPosition] = ()) -> PortfolioState:
    return PortfolioState(open_positions=tuple(positions))


__all__ = [
    "T0",
    "make_config",
    "make_evidence_snapshot",
    "make_mi_snapshot",
    "make_strategy_snapshot",
    "make_trade_result",
    "make_trade_history",
    "make_repeating_trade_history",
    "make_open_position",
    "make_portfolio_state",
]
