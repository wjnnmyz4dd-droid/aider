"""`ResearchSnapshot` assembly (ADR-029 §6)."""

from __future__ import annotations

from datetime import datetime
from typing import Tuple

from .models import (
    ComplianceEffectiveness,
    ExecutionQualitySummary,
    MarketIntelligenceReview,
    PerformanceAttribution,
    Ranking,
    Recommendation,
    ReportPeriod,
    ResearchSnapshot,
    RiskReview,
)


def build_research_snapshot(
    generated_at: datetime,
    period: ReportPeriod,
    period_start: datetime,
    period_end: datetime,
    sample_size: int,
    pair_rankings: Tuple[Ranking, ...],
    strategy_rankings: Tuple[Ranking, ...],
    session_rankings: Tuple[Ranking, ...],
    attributions: Tuple[PerformanceAttribution, ...],
    execution_quality: ExecutionQualitySummary,
    market_intelligence_review: MarketIntelligenceReview,
    risk_review: RiskReview,
    compliance_effectiveness: ComplianceEffectiveness,
    recommendations: Tuple[Recommendation, ...],
    warnings: Tuple[str, ...],
) -> ResearchSnapshot:
    return ResearchSnapshot(
        generated_at=generated_at, period=period, period_start=period_start, period_end=period_end,
        sample_size=sample_size, pair_rankings=pair_rankings, strategy_rankings=strategy_rankings,
        session_rankings=session_rankings, attributions=attributions, execution_quality=execution_quality,
        market_intelligence_review=market_intelligence_review, risk_review=risk_review,
        compliance_effectiveness=compliance_effectiveness, recommendations=recommendations, warnings=warnings,
    )


__all__ = ["build_research_snapshot"]
