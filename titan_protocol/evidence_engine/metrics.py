"""Evidence Engine metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading


class EvidenceEngineMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._evaluation_count = 0
        self._batch_evaluation_count = 0
        self._cache_hit_count = 0
        self._cache_miss_count = 0

    def record_evaluation(self) -> None:
        with self._lock:
            self._evaluation_count += 1

    def record_batch_evaluation(self) -> None:
        """Counts one `evaluate_batch()` call. Each pair inside that
        batch separately calls `record_evaluation()` via its own
        `evaluate()` invocation -- this counter is not added to
        `evaluation_count` to avoid double counting."""
        with self._lock:
            self._batch_evaluation_count += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self._cache_hit_count += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self._cache_miss_count += 1

    @property
    def evaluation_count(self) -> int:
        with self._lock:
            return self._evaluation_count

    @property
    def batch_evaluation_count(self) -> int:
        with self._lock:
            return self._batch_evaluation_count

    @property
    def cache_hit_count(self) -> int:
        with self._lock:
            return self._cache_hit_count

    @property
    def cache_miss_count(self) -> int:
        with self._lock:
            return self._cache_miss_count


__all__ = ["EvidenceEngineMetrics"]
