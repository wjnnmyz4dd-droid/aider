"""Position-tracking state (ADR-009 §2, §7, "track management state").

This is Position Manager's own analogue of `compliance_engine`'s
`ComplianceStateStore` and `execution_validator`'s `IdempotencyStore` —
a deliberate, narrow exception to the statelessness most stages
otherwise favor, explicitly authorized here by ADR-009 §2's "track
management state" responsibility. No durable/cross-restart persistence
is invented — ADR-009 does not require it (unlike Compliance Engine's
kill switch, `ADR-006` §14), only that lifecycle state, cooldown
timestamps, pending-request tracking, and one-time-action tracking are
available across `evaluate()` calls for the same position.

`has_pending_request`/`mark_pending`/`resolve_pending` implement
"duplicate management prevention" (ADR-009 Testing list): while a
position has a request in flight (awaiting MT5 Bridge confirmation), no
further request-producing rule is allowed to fire for it.

`has_taken_one_time_action`/`record_one_time_action` implement
idempotent one-shot rules (break-even, partial-close, time-exit,
emergency-close — ADR-009 §8: "re-evaluating an already-Protected
position does not re-issue the same adjustment").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .models import LifecycleState, ManagementAction


class PositionManagerStateStore(ABC):
    @abstractmethod
    def get_lifecycle_state(self, position_id: str) -> Optional[LifecycleState]:
        ...

    @abstractmethod
    def set_lifecycle_state(self, position_id: str, state: LifecycleState) -> None:
        ...

    @abstractmethod
    def last_action_at(self, position_id: str) -> Optional[datetime]:
        ...

    @abstractmethod
    def record_action(self, position_id: str, now: datetime) -> None:
        ...

    @abstractmethod
    def has_pending_request(self, position_id: str) -> bool:
        ...

    @abstractmethod
    def mark_pending(self, position_id: str) -> None:
        ...

    @abstractmethod
    def resolve_pending(self, position_id: str) -> None:
        ...

    @abstractmethod
    def has_taken_one_time_action(self, position_id: str, action: ManagementAction) -> bool:
        ...

    @abstractmethod
    def record_one_time_action(self, position_id: str, action: ManagementAction) -> None:
        ...


class InMemoryPositionManagerStateStore(PositionManagerStateStore):
    def __init__(self) -> None:
        self._lifecycle_state: dict = {}
        self._last_action_at: dict = {}
        self._pending: set = set()
        self._one_time_actions: dict = {}

    def get_lifecycle_state(self, position_id: str) -> Optional[LifecycleState]:
        return self._lifecycle_state.get(position_id)

    def set_lifecycle_state(self, position_id: str, state: LifecycleState) -> None:
        self._lifecycle_state[position_id] = state

    def last_action_at(self, position_id: str) -> Optional[datetime]:
        return self._last_action_at.get(position_id)

    def record_action(self, position_id: str, now: datetime) -> None:
        self._last_action_at[position_id] = now

    def has_pending_request(self, position_id: str) -> bool:
        return position_id in self._pending

    def mark_pending(self, position_id: str) -> None:
        self._pending.add(position_id)

    def resolve_pending(self, position_id: str) -> None:
        self._pending.discard(position_id)

    def has_taken_one_time_action(self, position_id: str, action: ManagementAction) -> bool:
        return action in self._one_time_actions.get(position_id, set())

    def record_one_time_action(self, position_id: str, action: ManagementAction) -> None:
        self._one_time_actions.setdefault(position_id, set()).add(action)
