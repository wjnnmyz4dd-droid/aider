"""Opportunity Selection Engine metrics surface.

Export-only: recording a metric has zero effect on any returned value.
"""

from __future__ import annotations

import threading


class OpportunitySelectionEngineMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scan_count = 0
        self._winner_count = 0
        self._tie_count = 0
        self._empty_candidate_set_count = 0
        self._incomplete_scan_suppression_count = 0
        self._selector_failure_count = 0

    def record_scan(self) -> None:
        with self._lock:
            self._scan_count += 1

    def record_winner(self) -> None:
        with self._lock:
            self._winner_count += 1

    def record_tie(self) -> None:
        with self._lock:
            self._tie_count += 1

    def record_empty_candidate_set(self) -> None:
        with self._lock:
            self._empty_candidate_set_count += 1

    def record_incomplete_scan_suppression(self) -> None:
        with self._lock:
            self._incomplete_scan_suppression_count += 1

    def record_selector_failure(self) -> None:
        with self._lock:
            self._selector_failure_count += 1

    @property
    def scan_count(self) -> int:
        with self._lock:
            return self._scan_count

    @property
    def winner_count(self) -> int:
        with self._lock:
            return self._winner_count

    @property
    def tie_count(self) -> int:
        with self._lock:
            return self._tie_count

    @property
    def empty_candidate_set_count(self) -> int:
        with self._lock:
            return self._empty_candidate_set_count

    @property
    def incomplete_scan_suppression_count(self) -> int:
        with self._lock:
            return self._incomplete_scan_suppression_count

    @property
    def selector_failure_count(self) -> int:
        with self._lock:
            return self._selector_failure_count


__all__ = ["OpportunitySelectionEngineMetrics"]
