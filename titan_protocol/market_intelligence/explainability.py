"""Explainability (ADR-025 §1 "Explainability").

Turns an already-computed `PairSafety`/`TradeReadiness` pair into the
seven human-readable `MarketIntelligenceExplanation` fields the task
names explicitly. Adds no new evidence and recomputes nothing.
"""

from __future__ import annotations

from .models import MarketIntelligenceExplanation, PairSafety, TradeReadiness


def build_explanation(pair_safety: PairSafety, trade_readiness: TradeReadiness) -> MarketIntelligenceExplanation:
    upcoming_events = tuple(
        f"{e.category.value} ({e.impact.value}) for {e.currency} at {e.scheduled_at.isoformat()}"
        for e in pair_safety.news.upcoming_events
    )

    restrictions = []
    if pair_safety.peg_policy.active:
        restrictions.append(
            f"peg/policy event active: {pair_safety.peg_policy.event_type.value if pair_safety.peg_policy.event_type else 'unknown'} -- {pair_safety.peg_policy.reason}"
        )
    if pair_safety.news.blackout_active:
        restrictions.append(f"news blackout: {pair_safety.news.blackout_reason}")
    if pair_safety.market_safety.market_closed:
        restrictions.append("market closed")
    if pair_safety.market_safety.trading_halted:
        restrictions.append("trading halted")
    if pair_safety.market_safety.broker_maintenance:
        restrictions.append("broker maintenance active")
    if pair_safety.market_safety.is_holiday:
        restrictions.append("holiday")
    if pair_safety.market_safety.is_early_close:
        restrictions.append("early market close")
    if pair_safety.market_safety.is_weekend_approaching:
        restrictions.append("weekend approaching")

    why_score_changed = (
        f"Pair Safety={pair_safety.pair_safety_score:.1f} "
        f"(news={pair_safety.news.news_score:.1f}, liquidity={pair_safety.liquidity.liquidity_score:.1f}, "
        f"session={pair_safety.session.session_score:.1f}, market_safety={pair_safety.market_safety.safety_score:.1f}, "
        f"peg_policy_active={pair_safety.peg_policy.active})"
    )

    return MarketIntelligenceExplanation(
        why_score_changed=why_score_changed,
        upcoming_events=upcoming_events,
        current_restrictions=tuple(restrictions),
        blackout_reason=pair_safety.news.blackout_reason,
        session_reason=pair_safety.session.reason,
        liquidity_reason=pair_safety.liquidity.reason,
        trade_readiness_explanation=(
            f"Trade Readiness={trade_readiness.readiness_score:.1f} (advisory only, does not approve trades) -- "
            + "; ".join(trade_readiness.reasons)
        ),
    )


__all__ = ["build_explanation"]
