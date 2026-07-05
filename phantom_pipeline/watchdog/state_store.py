"""The Watchdog's own bounded, non-durable operational state (ADR-011
§7, §8, §9, §11).

This is the Watchdog's own analogue of `position_manager.
PositionManagerStateStore` / `execution_validator.IdempotencyStore` — a
narrow, explicitly authorized exception to statelessness, holding only
heartbeat history, recovery-attempt history, freeze status, per-state
entry timestamps (for escalation-duration tracking, §11), and alert-dedup
signatures across calls for the same component. Not durable/SQLite —
ADR-011 does not require cross-restart persistence (unlike
`compliance_engine`'s kill switch, `ADR-006` §14) — only that this data
survive across calls within a running process.

Every collection here is bounded and pruned at write time (§9's
heartbeat-history discipline, mirrored here for recovery-attempt history
too) — the same "unbounded growth repeats a known defect class"
discipline `ADR-007` §7 / `ADR-008` §7 already established.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .models import AlertClass, HealthState, RecoveryActionType, RecoveryOutcome


class WatchdogStateStore(ABC):
    @abstractmethod
    def record_heartbeat(self, component: str, now: datetime, ttl_seconds: float, max_history: int) -> None:
        ...

    @abstractmethod
    def last_heartbeat_at(self, component: str) -> Optional[datetime]:
        ...

    @abstractmethod
    def heartbeat_history(self, component: str) -> Tuple[datetime, ...]:
        ...

    @abstractmethod
    def is_frozen(self, component: str) -> bool:
        ...

    @abstractmethod
    def freeze(self, component: str) -> None:
        ...

    @abstractmethod
    def clear_freeze(self, component: str) -> None:
        ...

    @abstractmethod
    def is_recovering(self, component: str) -> bool:
        ...

    @abstractmethod
    def set_recovering(self, component: str, in_progress: bool) -> None:
        ...

    @abstractmethod
    def record_recovery_attempt(self, component: str, now: datetime, window_seconds: float) -> None:
        ...

    @abstractmethod
    def attempts_in_window(self, component: str, now: datetime, window_seconds: float) -> int:
        ...

    @abstractmethod
    def last_attempt_at(self, component: str) -> Optional[datetime]:
        ...

    @abstractmethod
    def record_recovery_outcome(self, component: str, action: RecoveryActionType, outcome: RecoveryOutcome) -> None:
        ...

    @abstractmethod
    def last_action(self, component: str) -> Optional[RecoveryActionType]:
        ...

    @abstractmethod
    def last_outcome(self, component: str) -> Optional[RecoveryOutcome]:
        ...

    @abstractmethod
    def state_since(self, component: str) -> Optional[Tuple[HealthState, datetime]]:
        ...

    @abstractmethod
    def record_state(self, component: str, state: HealthState, now: datetime) -> None:
        ...

    @abstractmethod
    def last_alert_signature(self, component: str, alert_class: AlertClass) -> Optional[Tuple[str, datetime, int]]:
        ...

    @abstractmethod
    def record_alert(self, component: str, alert_class: AlertClass, detail: str, now: datetime, repeat_count: int) -> None:
        ...


class InMemoryWatchdogStateStore(WatchdogStateStore):
    def __init__(self) -> None:
        self._heartbeat_history: Dict[str, List[datetime]] = {}
        self._frozen: Set[str] = set()
        self._recovering: Set[str] = set()
        self._recovery_attempts: Dict[str, List[datetime]] = {}
        self._last_action: Dict[str, RecoveryActionType] = {}
        self._last_outcome: Dict[str, RecoveryOutcome] = {}
        self._state_since: Dict[str, Tuple[HealthState, datetime]] = {}
        self._last_alert: Dict[Tuple[str, AlertClass], Tuple[str, datetime, int]] = {}

    def record_heartbeat(self, component: str, now: datetime, ttl_seconds: float, max_history: int) -> None:
        history = self._heartbeat_history.setdefault(component, [])
        history.append(now)
        cutoff = now.timestamp() - ttl_seconds
        history[:] = [t for t in history if t.timestamp() >= cutoff][-max_history:]

    def last_heartbeat_at(self, component: str) -> Optional[datetime]:
        history = self._heartbeat_history.get(component)
        return history[-1] if history else None

    def heartbeat_history(self, component: str) -> Tuple[datetime, ...]:
        return tuple(self._heartbeat_history.get(component, []))

    def is_frozen(self, component: str) -> bool:
        return component in self._frozen

    def freeze(self, component: str) -> None:
        self._frozen.add(component)

    def clear_freeze(self, component: str) -> None:
        self._frozen.discard(component)

    def is_recovering(self, component: str) -> bool:
        return component in self._recovering

    def set_recovering(self, component: str, in_progress: bool) -> None:
        if in_progress:
            self._recovering.add(component)
        else:
            self._recovering.discard(component)

    def record_recovery_attempt(self, component: str, now: datetime, window_seconds: float) -> None:
        attempts = self._recovery_attempts.setdefault(component, [])
        attempts.append(now)
        cutoff = now.timestamp() - window_seconds
        attempts[:] = [t for t in attempts if t.timestamp() >= cutoff]

    def attempts_in_window(self, component: str, now: datetime, window_seconds: float) -> int:
        attempts = self._recovery_attempts.get(component, [])
        cutoff = now.timestamp() - window_seconds
        return len([t for t in attempts if t.timestamp() >= cutoff])

    def last_attempt_at(self, component: str) -> Optional[datetime]:
        attempts = self._recovery_attempts.get(component)
        return attempts[-1] if attempts else None

    def record_recovery_outcome(self, component: str, action: RecoveryActionType, outcome: RecoveryOutcome) -> None:
        self._last_action[component] = action
        self._last_outcome[component] = outcome

    def last_action(self, component: str) -> Optional[RecoveryActionType]:
        return self._last_action.get(component)

    def last_outcome(self, component: str) -> Optional[RecoveryOutcome]:
        return self._last_outcome.get(component)

    def state_since(self, component: str) -> Optional[Tuple[HealthState, datetime]]:
        return self._state_since.get(component)

    def record_state(self, component: str, state: HealthState, now: datetime) -> None:
        current = self._state_since.get(component)
        if current is None or current[0] != state:
            self._state_since[component] = (state, now)

    def last_alert_signature(self, component: str, alert_class: AlertClass) -> Optional[Tuple[str, datetime, int]]:
        return self._last_alert.get((component, alert_class))

    def record_alert(self, component: str, alert_class: AlertClass, detail: str, now: datetime, repeat_count: int) -> None:
        self._last_alert[(component, alert_class)] = (detail, now, repeat_count)
