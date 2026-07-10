"""System Reliability Engine metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading

from .models import DegradationLevel


class ReliabilityMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._heartbeat_count = 0
        self._cycle_report_count = 0
        self._cycles_observed = 0
        self._evaluation_count = 0
        self._degradation_counts = {level: 0 for level in DegradationLevel}
        self._recovery_attempts = 0
        self._recovery_successes = 0

    def record_heartbeat(self) -> None:
        with self._lock:
            self._heartbeat_count += 1

    def record_cycle_report(self, record_count: int) -> None:
        with self._lock:
            self._cycle_report_count += 1
            self._cycles_observed += record_count

    def record_evaluation(self, level: DegradationLevel) -> None:
        with self._lock:
            self._evaluation_count += 1
            self._degradation_counts[level] += 1

    def record_recovery_attempt(self, succeeded: bool) -> None:
        with self._lock:
            self._recovery_attempts += 1
            if succeeded:
                self._recovery_successes += 1

    @property
    def heartbeat_count(self) -> int:
        with self._lock:
            return self._heartbeat_count

    @property
    def evaluation_count(self) -> int:
        with self._lock:
            return self._evaluation_count

    @property
    def recovery_attempts(self) -> int:
        with self._lock:
            return self._recovery_attempts


__all__ = ["ReliabilityMetrics"]
