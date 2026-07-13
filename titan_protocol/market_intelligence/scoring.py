"""Pair Safety and Trade Readiness scoring (ADR-025 §1 "Pair Safety" /
"Trade Readiness").

Absolute blockers (an active peg/policy event, broker maintenance, a
trading halt, a closed market) hard-zero both scores -- they are never
blended proportionally with the other factors (ADR-025 Hard Rule 4).
An active news blackout hard-zeros Trade Readiness specifically, per
this phase's explicit "avoid high impact news" / "avoid central bank
announcements" instructions -- read as absolute avoidance, not a soft
weight reduction, consistent with this project's capital-preservation
priority.
"""

from __future__ import annotations

from typing import Tuple

from .config import MarketIntelligenceConfig
from .models import (
    LiquidityIntelligence,
    MarketSafetyStatus,
    PairNewsIntelligence,
    PairSafety,
    PegPolicyStatus,
    SessionIntelligence,
    TradeReadiness,
)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _is_absolute_blocker(market_safety: MarketSafetyStatus) -> bool:
    return market_safety.market_closed or market_safety.trading_halted or market_safety.broker_maintenance


def _absolute_blocker_reasons(market_safety: MarketSafetyStatus) -> Tuple[str, ...]:
    reasons = []
    if market_safety.market_closed:
        reasons.append("market closed")
    if market_safety.trading_halted:
        reasons.append("trading halted")
    if market_safety.broker_maintenance:
        reasons.append("broker maintenance active")
    return tuple(reasons)


def build_pair_safety(
    pair: str,
    news: PairNewsIntelligence,
    liquidity: LiquidityIntelligence,
    session: SessionIntelligence,
    market_safety: MarketSafetyStatus,
    peg_policy: PegPolicyStatus,
    config: MarketIntelligenceConfig,
) -> PairSafety:
    if peg_policy.active or _is_absolute_blocker(market_safety):
        score = 0.0
    else:
        score = _clamp(
            news.news_score * config.pair_safety_news_weight
            + liquidity.liquidity_score * config.pair_safety_liquidity_weight
            + session.session_score * config.pair_safety_session_weight
            + market_safety.safety_score * config.pair_safety_market_safety_weight
        )
    return PairSafety(
        pair=pair, news=news, liquidity=liquidity, session=session,
        market_safety=market_safety, peg_policy=peg_policy, pair_safety_score=score,
    )


def build_trade_readiness(pair_safety: PairSafety, config: MarketIntelligenceConfig) -> TradeReadiness:
    news = pair_safety.news
    liquidity = pair_safety.liquidity
    session = pair_safety.session
    market_safety = pair_safety.market_safety
    peg_policy = pair_safety.peg_policy

    if peg_policy.active:
        reason = f"blocked: peg/policy event active ({peg_policy.event_type.value if peg_policy.event_type else 'unknown'}) - {peg_policy.reason}"
        return TradeReadiness(pair=pair_safety.pair, readiness_score=0.0, reasons=(reason,))

    if _is_absolute_blocker(market_safety):
        reasons = tuple(f"blocked: {r}" for r in _absolute_blocker_reasons(market_safety))
        return TradeReadiness(pair=pair_safety.pair, readiness_score=0.0, reasons=reasons)

    if news.blackout_active:
        return TradeReadiness(pair=pair_safety.pair, readiness_score=0.0, reasons=(f"blocked: {news.blackout_reason}",))

    score = _clamp(
        pair_safety.pair_safety_score * config.readiness_pair_safety_weight
        + session.session_score * config.readiness_session_weight
        + liquidity.liquidity_score * config.readiness_liquidity_weight
        + news.news_score * config.readiness_news_weight
        + market_safety.safety_score * config.readiness_market_safety_weight
    )
    reasons = (
        f"pair_safety={pair_safety.pair_safety_score:.1f}",
        f"session={session.session_score:.1f} ({session.session.value})",
        f"liquidity={liquidity.liquidity_score:.1f}",
        f"news={news.news_score:.1f}",
        f"market_safety={market_safety.safety_score:.1f}",
    )
    return TradeReadiness(pair=pair_safety.pair, readiness_score=score, reasons=reasons)


__all__ = ["build_pair_safety", "build_trade_readiness"]
