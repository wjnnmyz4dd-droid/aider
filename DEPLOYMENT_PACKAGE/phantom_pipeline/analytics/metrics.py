"""Analytics-only metrics surface (ADR-010).

Export-only, additive — recording a metric has zero effect on any
returned output. No Dashboard, no Prometheus here — this is Analytics's
own metric surface only, the same discipline every prior stage's
metrics module already established.
"""

from __future__ import annotations

from typing import Dict


class AnalyticsMetrics:
    def __init__(self) -> None:
        self._collected_counts: Dict[str, int] = {}
        self._provenance_records_built: int = 0
        self._missing_event_count: int = 0
        self._performance_statistics_computed: int = 0
        self._replay_input_sets_built: int = 0

    def record_collected(self, kind: str) -> None:
        self._collected_counts[kind] = self._collected_counts.get(kind, 0) + 1

    def record_provenance_record_built(self) -> None:
        self._provenance_records_built += 1

    def record_missing_event(self) -> None:
        self._missing_event_count += 1

    def record_performance_statistics_computed(self) -> None:
        self._performance_statistics_computed += 1

    def record_replay_input_set_built(self) -> None:
        self._replay_input_sets_built += 1

    @property
    def collected_counts(self) -> Dict[str, int]:
        return dict(self._collected_counts)

    @property
    def provenance_records_built(self) -> int:
        return self._provenance_records_built

    @property
    def missing_event_count(self) -> int:
        return self._missing_event_count

    @property
    def performance_statistics_computed(self) -> int:
        return self._performance_statistics_computed

    @property
    def replay_input_sets_built(self) -> int:
        return self._replay_input_sets_built
