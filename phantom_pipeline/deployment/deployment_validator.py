"""Deployment Validator (Phase 5) — the 10 named go-live checks,
aggregated into a `DeploymentReadinessReport`.

Each check is an **injected probe** (`Callable[[], DeploymentCheckResult]`)
supplied by whoever wires the real deployment together (the one place
holding references to every real stage/service) — this module invents no
new authority and duplicates no existing one. In particular:

- `emergency_stop_functional` must be backed by a probe that exercises
  `PositionManager`'s own, already-implemented emergency-stop mechanism —
  `ManagementAction.EMERGENCY_CLOSE`, driven by
  `compliance_kill_switch_active` (`position_manager/checks.py`
  `emergency_close`) — e.g. by calling
  `PipelineOrchestrator.manage_position(..., compliance_kill_switch_active=True, ...)`
  against a live-but-isolated position and asserting the returned action
  is `EMERGENCY_CLOSE`. This module never implements a second kill switch.
- `paper_trading_disabled_in_live` should be backed by
  `ConfigurationManager.validate`'s own result for the LIVE profile
  (`paper_trading_enabled` must be `False`), not a second, independent
  reimplementation of that rule.

Each probe is called independently and never allowed to raise past this
module (an exception is treated as a failed check, fail-closed) — one
misbehaving probe never prevents the rest of the report from being
produced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping

from .models import DeploymentCheckResult, DeploymentProfile, DeploymentReadinessReport

REQUIRED_CHECK_NAMES = (
    "all_services_started",
    "all_ports_respond",
    "mt5_connected",
    "dashboard_online",
    "analytics_active",
    "watchdog_active",
    "paper_trading_disabled_in_live",
    "risk_limits_loaded",
    "compliance_active",
    "emergency_stop_functional",
)


class DeploymentValidator:
    def __init__(self, checks: Mapping[str, Callable[[], bool]]) -> None:
        self._checks = dict(checks)

    def run(self, profile: DeploymentProfile, now: datetime) -> DeploymentReadinessReport:
        results = []
        for name in REQUIRED_CHECK_NAMES:
            probe = self._checks.get(name)
            if probe is None:
                results.append(DeploymentCheckResult(name, False, "no probe registered for this check"))
                continue
            try:
                passed = bool(probe())
                detail = "passed" if passed else "failed"
            except Exception as exc:
                passed = False
                detail = f"probe raised: {exc!r}"
            results.append(DeploymentCheckResult(name, passed, detail))
        return DeploymentReadinessReport(profile=profile, checks=tuple(results), generated_at=now)


__all__ = ["DeploymentValidator", "REQUIRED_CHECK_NAMES"]
