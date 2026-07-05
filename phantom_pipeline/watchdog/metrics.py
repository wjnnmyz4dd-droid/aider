"""Watchdog-only metrics surface (ADR-011 §13).

Export-only, additive — recording a metric has zero effect on any
returned output. No Dashboard, no Prometheus, no Analytics here — this is
the Watchdog's own metric surface only, the same discipline every prior
stage's metrics module already established.
"""

from __future__ import annotations

from typing import Dict, List

from .models import HealthState, RecoveryOutcome


class WatchdogMetrics:
    def __init__(self) -> None:
        self._state_counts: Dict[str, int] = {}
        self._recovery_attempt_counts: Dict[str, int] = {}
        self._recovery_success_counts: Dict[str, int] = {}
        self._recovery_failure_counts: Dict[str, int] = {}
        self._restart_count: int = 0
        self._crash_count: int = 0
        self._dependency_failure_counts: Dict[str, int] = {}
        self._heartbeat_latencies_seconds: List[float] = []
        self._recovery_durations_seconds: List[float] = []

    def record_component_state(self, component: str, state: HealthState) -> None:
        self._state_counts[state.value] = self._state_counts.get(state.value, 0) + 1
        if state in (HealthState.CRITICAL, HealthState.OFFLINE):
            self._crash_count += 1

    def record_dependency_failure(self, component: str) -> None:
        self._dependency_failure_counts[component] = self._dependency_failure_counts.get(component, 0) + 1

    def record_heartbeat_latency(self, latency_seconds: float) -> None:
        self._heartbeat_latencies_seconds.append(latency_seconds)

    def record_recovery_attempt(self, component: str, outcome: RecoveryOutcome, duration_seconds: float = 0.0) -> None:
        self._recovery_attempt_counts[component] = self._recovery_attempt_counts.get(component, 0) + 1
        self._restart_count += 1
        self._recovery_durations_seconds.append(duration_seconds)
        if outcome == RecoveryOutcome.SUCCEEDED:
            self._recovery_success_counts[component] = self._recovery_success_counts.get(component, 0) + 1
        else:
            self._recovery_failure_counts[component] = self._recovery_failure_counts.get(component, 0) + 1

    @property
    def state_counts(self) -> Dict[str, int]:
        return dict(self._state_counts)

    @property
    def restart_count(self) -> int:
        return self._restart_count

    @property
    def crash_count(self) -> int:
        return self._crash_count

    @property
    def dependency_failure_counts(self) -> Dict[str, int]:
        return dict(self._dependency_failure_counts)

    @property
    def average_heartbeat_latency_seconds(self) -> float:
        if not self._heartbeat_latencies_seconds:
            return 0.0
        return sum(self._heartbeat_latencies_seconds) / len(self._heartbeat_latencies_seconds)

    @property
    def average_recovery_time_seconds(self) -> float:
        if not self._recovery_durations_seconds:
            return 0.0
        return sum(self._recovery_durations_seconds) / len(self._recovery_durations_seconds)

    @property
    def recovery_success_rate(self) -> float:
        total = sum(self._recovery_success_counts.values()) + sum(self._recovery_failure_counts.values())
        if total == 0:
            return 0.0
        return sum(self._recovery_success_counts.values()) / total
