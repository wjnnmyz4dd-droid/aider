"""Market Intelligence Engine metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading


class MarketIntelligenceMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._evaluation_count = 0
        self._batch_evaluation_count = 0
        self._cache_access_count = 0

    def record_evaluation(self) -> None:
        with self._lock:
            self._evaluation_count += 1

    def record_batch_evaluation(self) -> None:
        with self._lock:
            self._batch_evaluation_count += 1

    def record_cache_access(self) -> None:
        with self._lock:
            self._cache_access_count += 1

    @property
    def evaluation_count(self) -> int:
        with self._lock:
            return self._evaluation_count

    @property
    def batch_evaluation_count(self) -> int:
        with self._lock:
            return self._batch_evaluation_count

    @property
    def cache_access_count(self) -> int:
        with self._lock:
            return self._cache_access_count


__all__ = ["MarketIntelligenceMetrics"]
