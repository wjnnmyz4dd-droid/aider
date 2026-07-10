"""Shared test-only fixtures for the Research & Learning Engine test
suite -- hand-constructs `ClosedTrade`/`ClosedTradeHistory` directly
(same rationale as every prior engine's `_fixtures.py` this session)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from phantom.compliance_engine.models import ComplianceDecision
from phantom.evidence_engine.models import CandlestickPattern, SessionName
from phantom.market_intelligence.models import NewsCategory
from phantom.research_engine.config import ResearchEngineConfig
from phantom.research_engine.models import (
    ClosedTrade,
    ClosedTradeHistory,
    SRInteraction,
    TrendVsRange,
    VolatilityBucket,
)
from phantom.strategy_engine.models import MarketRegime, StrategyId

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap


def make_config(**overrides) -> ResearchEngineConfig:
    return ResearchEngineConfig(**overrides)


def make_executed_trade(
    index: int = 0,
    pair: str = "EURUSD",
    strategy_id: Optional[StrategyId] = StrategyId.TREND_CONTINUATION,
    market_regime: Optional[MarketRegime] = MarketRegime.TRENDING,
    trend_vs_range: Optional[TrendVsRange] = None,
    session: Optional[SessionName] = SessionName.LONDON,
    won: bool = True,
    r_multiple: Optional[float] = None,
    evidence_score: float = 90.0,
    market_intelligence_score: float = 85.0,
    trade_readiness_score: float = 80.0,
    risk_confidence_tier: Optional[str] = "TIER_5",
    risk_r: float = 1.0,
    kelly_was_binding: bool = False,
    portfolio_heat_at_entry_r: Optional[float] = 1.5,
    was_correlated_with_open_position: bool = False,
    compliance_decision: Optional[ComplianceDecision] = ComplianceDecision.APPROVE,
    approved_size_r: float = 1.0,
    volatility_bucket: VolatilityBucket = VolatilityBucket.NORMAL,
    news_category: Optional[NewsCategory] = None,
    news_blackout_was_active: bool = False,
    peg_policy_was_active: bool = False,
    holiday_was_active: bool = False,
    candlestick_pattern: Optional[CandlestickPattern] = None,
    support_resistance_interaction: SRInteraction = SRInteraction.NONE,
    liquidity_sweep_occurred: bool = False,
    bos_fvg_occurred: bool = False,
    slippage_entry_pips: float = 0.2,
    slippage_exit_pips: float = 0.1,
    spread_at_entry: float = 1.0,
    spread_at_exit: float = 1.0,
    time_to_fill_ms: float = 300.0,
    requotes: int = 0,
    partial_fills: int = 0,
    opened_at: Optional[datetime] = None,
) -> ClosedTrade:
    opened = opened_at if opened_at is not None else T0 + timedelta(hours=index)
    r = r_multiple if r_multiple is not None else (2.0 if won else -1.0)
    return ClosedTrade(
        pair=pair, strategy_id=strategy_id, market_regime=market_regime, trend_vs_range=trend_vs_range,
        evidence_score=evidence_score, market_intelligence_score=market_intelligence_score,
        trade_readiness_score=trade_readiness_score, risk_confidence_tier=risk_confidence_tier, risk_r=risk_r,
        kelly_was_binding=kelly_was_binding, portfolio_heat_at_entry_r=portfolio_heat_at_entry_r,
        was_correlated_with_open_position=was_correlated_with_open_position,
        compliance_decision=compliance_decision, approved_size_r=approved_size_r,
        evaluated_at=opened, session=session,
        won=won, entry_price=1.1000, exit_price=1.1020 if r > 0 else 1.0990,
        stop_loss_price=1.0990, take_profit_price=1.1020, r_multiple=r,
        opened_at=opened, closed_at=opened + timedelta(minutes=30),
        requested_entry_price=1.1000, slippage_entry_pips=slippage_entry_pips, slippage_exit_pips=slippage_exit_pips,
        spread_at_entry=spread_at_entry, spread_at_exit=spread_at_exit, time_to_fill_ms=time_to_fill_ms,
        partial_fills=partial_fills, requotes=requotes,
        news_category=news_category, news_blackout_was_active=news_blackout_was_active,
        peg_policy_was_active=peg_policy_was_active, holiday_was_active=holiday_was_active,
        volatility_bucket=volatility_bucket, candlestick_pattern=candlestick_pattern,
        support_resistance_interaction=support_resistance_interaction,
        liquidity_sweep_occurred=liquidity_sweep_occurred, bos_fvg_occurred=bos_fvg_occurred,
    )


def make_rejected_trade(
    index: int = 0,
    pair: str = "EURUSD",
    strategy_id: Optional[StrategyId] = StrategyId.TREND_CONTINUATION,
    session: Optional[SessionName] = SessionName.LONDON,
    evaluated_at: Optional[datetime] = None,
) -> ClosedTrade:
    return ClosedTrade(
        pair=pair, strategy_id=strategy_id, market_regime=MarketRegime.TRENDING, trend_vs_range=None,
        evidence_score=60.0, market_intelligence_score=70.0, trade_readiness_score=65.0,
        risk_confidence_tier=None, risk_r=0.0, kelly_was_binding=False, portfolio_heat_at_entry_r=None,
        was_correlated_with_open_position=False, compliance_decision=ComplianceDecision.REJECT, approved_size_r=0.0,
        evaluated_at=evaluated_at if evaluated_at is not None else T0 + timedelta(hours=index), session=session,
    )


def make_trade_history(trades: Sequence[ClosedTrade] = ()) -> ClosedTradeHistory:
    return ClosedTradeHistory(results=tuple(trades))


def make_repeating_executed_trades(
    count: int = 30,
    win_r: float = 2.0,
    loss_r: float = -1.0,
    win_rate: float = 0.5,
    pair: str = "EURUSD",
    strategy_id: Optional[StrategyId] = StrategyId.TREND_CONTINUATION,
    session: Optional[SessionName] = SessionName.LONDON,
    start: datetime = T0,
    spacing: timedelta = timedelta(hours=1),
) -> List[ClosedTrade]:
    """A deterministic alternating-outcome trade sequence: exactly
    `round(count * win_rate)` wins, spaced evenly, oldest first."""

    num_wins = round(count * win_rate)
    trades = []
    for i in range(count):
        won = i % 2 == 0 and (i // 2) < num_wins
        r = win_r if won else loss_r
        trades.append(make_executed_trade(
            index=i, pair=pair, strategy_id=strategy_id, session=session, won=won, r_multiple=r,
            opened_at=start + spacing * i,
        ))
    return trades


__all__ = [
    "T0",
    "make_config",
    "make_executed_trade",
    "make_rejected_trade",
    "make_trade_history",
    "make_repeating_executed_trades",
]
