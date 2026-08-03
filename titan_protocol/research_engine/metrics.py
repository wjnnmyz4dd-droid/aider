"""Research Engine metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading


class ResearchEngineMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._evaluation_count = 0
        self._recommendation_count = 0

    def record_evaluation(self) -> None:
        with self._lock:
            self._evaluation_count += 1

    def record_recommendations(self, count: int) -> None:
        with self._lock:
            self._recommendation_count += count

    @property
    def evaluation_count(self) -> int:
        with self._lock:
            return self._evaluation_count

    @property
    def recommendation_count(self) -> int:
        with self._lock:
            return self._recommendation_count


__all__ = ["ResearchEngineMetrics"]
