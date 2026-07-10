"""`StrategySnapshot` assembly (ADR-026 §1 "Outputs"). Adds no new
evidence and recomputes nothing -- it only narrates the qualification
results and the winning-strategy decision it's given.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from phantom.evidence_engine.models import EvidenceSnapshot
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from .models import QualificationResult, StrategySnapshot, WinningStrategy


def _rejection_reason(qualifications: Sequence[QualificationResult]) -> str:
    qualified = [q for q in qualifications if q.status.value == "QUALIFIED"]
    if not qualified:
        return "No strategy qualified for this pair under current conditions"
    return f"{len(qualified)} strategies qualified but remained tied through every selection step -- rejected, not randomized"


def _evidence_summary(evidence: EvidenceSnapshot) -> str:
    return (
        f"Evidence composite={evidence.report.score.composite:.1f}, "
        f"trend={evidence.structure.trend.value}, "
        f"{len(evidence.structure.events)} structure event(s), "
        f"{len(evidence.liquidity.sweeps)} liquidity sweep(s), "
        f"{len(evidence.candlesticks)} candlestick pattern(s), "
        f"{len(evidence.fair_value_gaps)} fair value gap(s)"
    )


def _market_intelligence_summary(market_intelligence: MarketIntelligenceSnapshot) -> str:
    return (
        f"Pair Safety={market_intelligence.pair_safety.pair_safety_score:.1f}, "
        f"Trade Readiness={market_intelligence.trade_readiness.readiness_score:.1f} (advisory only), "
        f"session={market_intelligence.pair_safety.session.session.value}, "
        f"news_blackout={market_intelligence.pair_safety.news.blackout_active}, "
        f"peg_policy_active={market_intelligence.pair_safety.peg_policy.active}"
    )


def build_strategy_snapshot(
    pair: str,
    now: datetime,
    qualifications: Sequence[QualificationResult],
    winning_strategy: Optional[WinningStrategy],
    evidence: EvidenceSnapshot,
    market_intelligence: MarketIntelligenceSnapshot,
) -> StrategySnapshot:
    rejected = winning_strategy is None
    return StrategySnapshot(
        pair=pair,
        generated_at=now,
        winning_strategy=winning_strategy,
        all_qualifications=tuple(qualifications),
        rejected=rejected,
        rejection_reason=_rejection_reason(qualifications) if rejected else None,
        supporting_evidence_summary=_evidence_summary(evidence),
        supporting_market_intelligence_summary=_market_intelligence_summary(market_intelligence),
    )


__all__ = ["build_strategy_snapshot"]
