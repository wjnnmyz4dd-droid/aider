"""Execution-Validator-only metrics surface (ADR-007 §11).

Export-only: recording a metric has zero effect on any returned
`ExecutionDecision` — the same "additive, changes nothing" discipline
every prior stage's metrics module already established. No Dashboard, no
Prometheus, no Analytics here — this is the Execution Validator's own
metric surface only.

`blocks_by_check` increments once per *every* blocking check named in a
REJECT decision's `blocking_reasons` — not only the first — matching the
non-under-attributing design already adopted for Compliance Engine's own
`blocks_by_check` (ADR-006 metrics), itself a fix for a Recommended
finding on Risk Engine's `zero_risk_by_reason`.
"""

from __future__ import annotations

from typing import Dict, List

from .models import ExecutionDecision, Verdict


class ExecutionValidatorMetrics:
    def __init__(self) -> None:
        self._decisions_by_verdict: Dict[str, int] = {}
        self._blocks_by_check: Dict[str, int] = {}
        self._validation_latencies_seconds: List[float] = []
        self._duplicate_prevention_count: int = 0

    def record_decision(self, decision: ExecutionDecision, latency_seconds: float = 0.0) -> None:
        self._decisions_by_verdict[decision.verdict.value] = (
            self._decisions_by_verdict.get(decision.verdict.value, 0) + 1
        )
        self._validation_latencies_seconds.append(latency_seconds)
        if decision.verdict == Verdict.REJECT:
            for check in decision.blocking_reasons:
                self._blocks_by_check[check] = self._blocks_by_check.get(check, 0) + 1
                if check == "NO_DUPLICATE_REQUEST":
                    self._duplicate_prevention_count += 1

    @property
    def decisions_by_verdict(self) -> Dict[str, int]:
        return dict(self._decisions_by_verdict)

    @property
    def blocks_by_check(self) -> Dict[str, int]:
        return dict(self._blocks_by_check)

    @property
    def duplicate_prevention_count(self) -> int:
        return self._duplicate_prevention_count

    @property
    def average_validation_latency_seconds(self) -> float:
        if not self._validation_latencies_seconds:
            return 0.0
        return sum(self._validation_latencies_seconds) / len(self._validation_latencies_seconds)

    @property
    def approval_rate(self) -> float:
        total = sum(self._decisions_by_verdict.values())
        if total == 0:
            return 0.0
        return self._decisions_by_verdict.get(Verdict.APPROVE.value, 0) / total
