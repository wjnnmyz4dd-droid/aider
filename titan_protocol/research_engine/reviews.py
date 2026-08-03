"""Market Intelligence Review, Risk Review, and Compliance Effectiveness
(ADR-029 §5) -- all three built on `effectiveness.py`'s shared
bucket-comparison helper."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from titan_protocol.compliance_engine.models import ComplianceDecision

from .config import ResearchEngineConfig
from .effectiveness import bucket_by_score_tertiles, compare_buckets
from .models import ClosedTrade, ComplianceEffectiveness, EffectivenessComparison, MarketIntelligenceReview, RiskReview


def _split(trades: Sequence[ClosedTrade], predicate) -> Tuple[List[ClosedTrade], List[ClosedTrade]]:
    matching = [t for t in trades if predicate(t)]
    not_matching = [t for t in trades if not predicate(t)]
    return not_matching, matching  # (baseline, comparison)


def _describe(comparison: EffectivenessComparison, subject: str) -> List[str]:
    if not comparison.notable or comparison.delta is None:
        return []
    direction = "worse" if comparison.delta < 0 else "better"
    return [f"{subject} performs {direction} than baseline (delta {comparison.delta:+.2f}R) -- review the current configuration."]


def review_market_intelligence(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> MarketIntelligenceReview:
    baseline, blackout = _split(trades, lambda t: t.news_blackout_was_active)
    news_blackout_effectiveness = compare_buckets("news_blackout_active_vs_inactive", baseline, blackout, config)

    baseline, peg = _split(trades, lambda t: t.peg_policy_was_active)
    peg_protection_effectiveness = compare_buckets("peg_policy_active_vs_inactive", baseline, peg, config)

    baseline, holiday = _split(trades, lambda t: t.holiday_was_active)
    holiday_restriction_effectiveness = compare_buckets("holiday_active_vs_inactive", baseline, holiday, config)

    liquidity_scoring_effectiveness = (
        bucket_by_score_tertiles(trades, lambda t: t.market_intelligence_score, "market_intelligence_score_low_vs_high", config),
    )
    session_scoring_effectiveness = (
        bucket_by_score_tertiles(trades, lambda t: t.trade_readiness_score, "trade_readiness_score_low_vs_high", config),
    )

    recommendations: List[str] = []
    recommendations += _describe(news_blackout_effectiveness, "Trading during news blackout windows")
    recommendations += _describe(peg_protection_effectiveness, "Trading during peg/policy events")
    recommendations += _describe(holiday_restriction_effectiveness, "Trading during holiday periods")

    return MarketIntelligenceReview(
        news_blackout_effectiveness=news_blackout_effectiveness,
        peg_protection_effectiveness=peg_protection_effectiveness,
        holiday_restriction_effectiveness=holiday_restriction_effectiveness,
        liquidity_scoring_effectiveness=liquidity_scoring_effectiveness,
        session_scoring_effectiveness=session_scoring_effectiveness,
        recommendations=tuple(recommendations),
    )


def review_risk(trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> RiskReview:
    tiers: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        if trade.risk_confidence_tier:
            tiers[trade.risk_confidence_tier].append(trade)
    confidence_scaling_effectiveness = tuple(
        compare_buckets(f"confidence_tier_{name}_vs_overall", trades, group, config) for name, group in sorted(tiers.items())
    )

    volatility_groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        volatility_groups[trade.volatility_bucket.value].append(trade)
    volatility_scaling_effectiveness = tuple(
        compare_buckets(f"volatility_{name}_vs_overall", trades, group, config) for name, group in sorted(volatility_groups.items())
    )

    baseline, kelly_bound = _split(trades, lambda t: t.kelly_was_binding)
    kelly_cap_effectiveness = compare_buckets("kelly_binding_vs_not", baseline, kelly_bound, config)

    heat_effectiveness = bucket_by_score_tertiles(
        [t for t in trades if t.portfolio_heat_at_entry_r is not None],
        lambda t: t.portfolio_heat_at_entry_r, "portfolio_heat_low_vs_high", config,
    )
    baseline, correlated = _split(trades, lambda t: t.was_correlated_with_open_position)
    correlation_effectiveness = compare_buckets("correlated_vs_uncorrelated", baseline, correlated, config)
    portfolio_heat_effectiveness = (heat_effectiveness, correlation_effectiveness)

    recommendations: List[str] = []
    recommendations += _describe(kelly_cap_effectiveness, "Trades where the Kelly cap was the binding size constraint")
    recommendations += _describe(correlation_effectiveness, "Trades correlated with an already-open position")

    return RiskReview(
        confidence_scaling_effectiveness=confidence_scaling_effectiveness,
        volatility_scaling_effectiveness=volatility_scaling_effectiveness,
        kelly_cap_effectiveness=kelly_cap_effectiveness,
        portfolio_heat_effectiveness=portfolio_heat_effectiveness,
        recommendations=tuple(recommendations),
    )


def review_compliance(all_trades: Sequence[ClosedTrade], config: ResearchEngineConfig) -> ComplianceEffectiveness:
    """`all_trades` is the *full* `ClosedTradeHistory` including
    rejected candidates -- rejection rate can only be measured by
    seeing the rejections themselves, unlike every other review in this
    module (ADR-029 §3)."""

    approved = [t for t in all_trades if t.compliance_decision is ComplianceDecision.APPROVE]
    reduced = [t for t in all_trades if t.compliance_decision is ComplianceDecision.REDUCE]
    rejection_count = sum(1 for t in all_trades if t.compliance_decision is ComplianceDecision.REJECT)
    approve_vs_reduce = compare_buckets("approve_vs_reduce", approved, reduced, config)

    rejection_rate = rejection_count / len(all_trades) if all_trades else 0.0

    recommendations = list(_describe(approve_vs_reduce, "Reduced trades relative to fully-approved trades"))

    return ComplianceEffectiveness(
        approve_vs_reduce=approve_vs_reduce, rejection_count=rejection_count,
        rejection_rate=rejection_rate, recommendations=tuple(recommendations),
    )


__all__ = ["review_market_intelligence", "review_risk", "review_compliance"]
