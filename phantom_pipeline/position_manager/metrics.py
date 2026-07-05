"""Position-Manager-only metrics surface (ADR-009 §13).

Export-only, additive — recording a metric has zero effect on any
returned output. No Dashboard, no Prometheus, no Analytics here — this
is the Position Manager's own metric surface only, the same discipline
every prior stage's metrics module already established.
"""

from __future__ import annotations

from typing import Dict, List

from .models import LifecycleState, ManagementAction


class PositionManagerMetrics:
    def __init__(self) -> None:
        self._open_position_ids: set = set()
        self._positions_by_state: Dict[str, int] = {}
        self._action_counts: Dict[str, int] = {}
        self._recovered_count: int = 0
        self._recovered_after_disconnect_count: int = 0
        self._position_durations_seconds: List[float] = []

    def record_open_position(self, position_id: str) -> None:
        self._open_position_ids.add(position_id)

    def record_closed_position(self, position_id: str, duration_seconds: float) -> None:
        self._open_position_ids.discard(position_id)
        self._position_durations_seconds.append(duration_seconds)

    def record_lifecycle_state(self, state: LifecycleState) -> None:
        self._positions_by_state[state.value] = self._positions_by_state.get(state.value, 0) + 1
        if state == LifecycleState.RECOVERED:
            self._recovered_count += 1
        elif state == LifecycleState.RECOVERED_AFTER_DISCONNECT:
            self._recovered_after_disconnect_count += 1

    def record_action(self, action: ManagementAction) -> None:
        self._action_counts[action.value] = self._action_counts.get(action.value, 0) + 1

    @property
    def open_position_count(self) -> int:
        return len(self._open_position_ids)

    @property
    def positions_by_state(self) -> Dict[str, int]:
        return dict(self._positions_by_state)

    @property
    def action_counts(self) -> Dict[str, int]:
        return dict(self._action_counts)

    @property
    def recovered_count(self) -> int:
        return self._recovered_count

    @property
    def recovered_after_disconnect_count(self) -> int:
        return self._recovered_after_disconnect_count

    @property
    def average_position_duration_seconds(self) -> float:
        if not self._position_durations_seconds:
            return 0.0
        return sum(self._position_durations_seconds) / len(self._position_durations_seconds)
