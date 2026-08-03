"""The bounded infrastructure-recovery boundary (ADR-011 §7, §15).

`RecoveryActionExecutor` is the sole abstraction through which the
Watchdog performs any of the 8 named, bounded recovery actions (§7) —
never inline OS/process control. No dedicated process-control module
exists anywhere in this repository (mirroring `mt5_bridge.broker_adapter
.BrokerAdapter`'s own justification for MT5 communication, `ADR-008`
§16) — Phase 1 ships `FakeRecoveryActionExecutor`, a fully deterministic,
in-memory test double, the same "no live external dependency in unit
tests" discipline established for every other stage. A real executor
wrapping actual OS process/service control is future work, not invented
here.

The executor never holds broker credentials, never places orders, and
never touches a trading decision (§15) — its only capability is
attempting one of the 8 named `RecoveryActionType` values and reporting
success or failure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Tuple

from .models import RecoveryActionType


class RecoveryActionExecutor(ABC):
    @abstractmethod
    def execute(self, component: str, action: RecoveryActionType) -> bool:
        """Attempt the given bounded recovery action for `component`.
        Returns True on success, False on failure. Never raises for an
        ordinary failure — a failed attempt is a normal, expected outcome
        the Watchdog's own fail-safe behavior (§8) already handles."""
        ...


class FakeRecoveryActionExecutor(RecoveryActionExecutor):
    """A deterministic, fully scriptable in-memory recovery double for
    tests. Nothing here touches any real process, service, or
    connection — every outcome is either programmed in advance via
    `set_result`, or a fixed deterministic default (success)."""

    def __init__(self, default_result: bool = True) -> None:
        self._default_result = default_result
        self._scripted_results: Dict[Tuple[str, RecoveryActionType], bool] = {}
        self.attempts: list = []

    def set_result(self, component: str, action: RecoveryActionType, result: bool) -> None:
        self._scripted_results[(component, action)] = result

    def execute(self, component: str, action: RecoveryActionType) -> bool:
        self.attempts.append((component, action))
        return self._scripted_results.get((component, action), self._default_result)
