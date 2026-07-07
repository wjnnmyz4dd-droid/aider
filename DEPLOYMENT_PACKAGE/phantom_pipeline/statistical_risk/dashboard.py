"""Statistical Risk Dashboard builder (`ADR-022` Amendment 1 §A1.2 item
6).

Mirrors `research_desk.dashboard.ResearchDeskDashboardBuilder`'s own
precedent exactly: a new, additive snapshot type owned by this package,
never an eleventh `dashboard.models.ViewName` value and never a
modification to `dashboard/`. Every field is read from an
already-produced `StatisticalRiskAssessment`/`ConfidenceInterval` — this
module computes no new statistic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from .models import (
    SCHEMA_VERSION,
    ConfidenceInterval,
    StatisticalRiskAssessment,
    StatisticalRiskDashboardSnapshot,
    StatisticalRiskTrendPoint,
)


def trend_point_from_assessment(
    assessment: StatisticalRiskAssessment, timestamp: datetime, kelly_recommendation: Optional[float] = None
) -> StatisticalRiskTrendPoint:
    return StatisticalRiskTrendPoint(
        trace_id=assessment.trace_id,
        timestamp=timestamp,
        risk_of_ruin=assessment.risk_of_ruin,
        value_at_risk=assessment.value_at_risk,
        conditional_value_at_risk=assessment.conditional_value_at_risk,
        sharpe_ratio=assessment.sharpe_ratio,
        sortino_ratio=assessment.sortino_ratio,
        rolling_expectancy=assessment.rolling_expectancy,
        portfolio_heat=assessment.portfolio_heat,
        kelly_recommendation=kelly_recommendation,
        volatility_state=assessment.volatility_state,
        correlation_state=assessment.correlation_state,
        statistical_recommendation=assessment.statistical_recommendation,
    )


class StatisticalRiskDashboardBuilder:
    def build(
        self,
        now: datetime,
        latest_assessment: Optional[StatisticalRiskAssessment] = None,
        latest_kelly_recommendation: Optional[float] = None,
        historical_trend: Sequence[StatisticalRiskTrendPoint] = (),
        confidence_interval: Optional[ConfidenceInterval] = None,
    ) -> StatisticalRiskDashboardSnapshot:
        return StatisticalRiskDashboardSnapshot(
            schema_version=SCHEMA_VERSION,
            generated_at=now,
            latest_assessment=latest_assessment,
            latest_kelly_recommendation=latest_kelly_recommendation,
            historical_trend=tuple(historical_trend),
            confidence_interval=confidence_interval,
        )


__all__ = ["StatisticalRiskDashboardBuilder", "trend_point_from_assessment"]
