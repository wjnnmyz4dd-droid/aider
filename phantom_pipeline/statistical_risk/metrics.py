"""Statistical-Risk-only metrics surface (`ADR-022` §4).

Export-only: recording a metric has zero effect on any returned
`StatisticalRiskAssessment` — the same "additive, changes nothing"
discipline every prior stage's metrics module already established.
"""

from __future__ import annotations

from typing import Dict

from .models import StatisticalRiskAssessment


class StatisticalRiskMetrics:
    def __init__(self) -> None:
        self._assessments_by_recommendation: Dict[str, int] = {}
        self._assessment_count = 0

    def record_assessment(self, assessment: StatisticalRiskAssessment) -> None:
        self._assessment_count += 1
        key = assessment.statistical_recommendation.value
        self._assessments_by_recommendation[key] = self._assessments_by_recommendation.get(key, 0) + 1

    @property
    def assessment_count(self) -> int:
        return self._assessment_count

    @property
    def assessments_by_recommendation(self) -> Dict[str, int]:
        return dict(self._assessments_by_recommendation)


__all__ = ["StatisticalRiskMetrics"]
