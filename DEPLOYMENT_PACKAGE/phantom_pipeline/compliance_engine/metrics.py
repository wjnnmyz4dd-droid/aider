"""Compliance-Engine-only metrics surface (ADR-006 §17).

Export-only: recording a metric has zero effect on any returned
`ComplianceDecision` — the same "additive, changes nothing" discipline
every prior stage's metrics module already established. No Dashboard, no
Prometheus, no Analytics here — this is the Compliance Engine's own
metric surface only.

`blocks_by_check` increments once per *every* blocking check named in a
BLOCK decision's `blocking_rules` — not only the first — so a decision
blocked by two simultaneous checks credits both, avoiding the
under-attribution the Risk Engine's own `zero_risk_by_reason` metric was
found to have (ADR-005 audit, Recommended finding).
"""

from __future__ import annotations

from typing import Dict

from .models import ComplianceDecision, Verdict


class ComplianceEngineMetrics:
    def __init__(self) -> None:
        self._decisions_by_verdict: Dict[str, int] = {}
        self._blocks_by_check: Dict[str, int] = {}
        self._kill_switch_active: bool = False
        self._daily_lockout_active: bool = False

    def record_decision(self, decision: ComplianceDecision) -> None:
        self._decisions_by_verdict[decision.verdict.value] = (
            self._decisions_by_verdict.get(decision.verdict.value, 0) + 1
        )
        if decision.verdict == Verdict.BLOCK:
            for check in decision.blocking_rules:
                self._blocks_by_check[check] = self._blocks_by_check.get(check, 0) + 1

    def set_kill_switch_active(self, active: bool) -> None:
        self._kill_switch_active = active

    def set_daily_lockout_active(self, active: bool) -> None:
        self._daily_lockout_active = active

    @property
    def decisions_by_verdict(self) -> Dict[str, int]:
        return dict(self._decisions_by_verdict)

    @property
    def blocks_by_check(self) -> Dict[str, int]:
        return dict(self._blocks_by_check)

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def daily_lockout_active(self) -> bool:
        return self._daily_lockout_active
