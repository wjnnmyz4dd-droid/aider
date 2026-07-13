"""Validation Engine metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading


class ValidationEngineMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._evaluation_count = 0
        self._failure_count = 0

    def record_evaluation(self) -> None:
        with self._lock:
            self._evaluation_count += 1

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1

    @property
    def evaluation_count(self) -> int:
        with self._lock:
            return self._evaluation_count

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count


__all__ = ["ValidationEngineMetrics"]
