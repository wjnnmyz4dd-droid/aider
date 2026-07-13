"""Runtime metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading


class RuntimeMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cycle_count = 0
        self._failure_count = 0

    def record_cycle(self) -> None:
        with self._lock:
            self._cycle_count += 1

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1

    @property
    def cycle_count(self) -> int:
        with self._lock:
            return self._cycle_count

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count


__all__ = ["RuntimeMetrics"]
