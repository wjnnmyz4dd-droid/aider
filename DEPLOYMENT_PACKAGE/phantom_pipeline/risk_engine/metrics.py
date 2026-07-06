"""Risk-Engine-only metrics surface (ADR-005 §17).

Export-only: recording a metric has zero effect on any returned
`RiskDecision` — the same "additive, changes nothing" discipline every
prior stage's metrics module already established. No Dashboard, no
Prometheus, no Analytics here — this is the Risk Engine's own metric
surface only.
"""

from __future__ import annotations

from typing import Dict, List

from .models import RiskDecision


class RiskEngineMetrics:
    def __init__(self) -> None:
        self._decisions_by_tier: Dict[str, int] = {}
        self._awarded_risk_percentages: List[float] = []
        self._zero_risk_by_reason: Dict[str, int] = {}

    def record_decision(self, decision: RiskDecision) -> None:
        self._decisions_by_tier[decision.risk_tier.value] = (
            self._decisions_by_tier.get(decision.risk_tier.value, 0) + 1
        )
        self._awarded_risk_percentages.append(decision.approved_risk_percent)

        if decision.approved_risk_percent == 0.0:
            reason = decision.reason_codes[0] if decision.reason_codes else "unspecified"
            self._zero_risk_by_reason[reason] = self._zero_risk_by_reason.get(reason, 0) + 1

    @property
    def decisions_by_tier(self) -> Dict[str, int]:
        return dict(self._decisions_by_tier)

    @property
    def awarded_risk_percentages(self) -> List[float]:
        return list(self._awarded_risk_percentages)

    @property
    def zero_risk_by_reason(self) -> Dict[str, int]:
        return dict(self._zero_risk_by_reason)
