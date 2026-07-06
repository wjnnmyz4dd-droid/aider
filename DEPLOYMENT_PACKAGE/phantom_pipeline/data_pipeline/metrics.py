"""Data-Pipeline-only metrics surface (ADR-013 §15).

Export-only, additive — recording a metric has zero effect on any
returned output, the same discipline every other stage's metrics module
already established (`scanner.metrics`, `watchdog.metrics`, etc.). This
was the one package in `phantom_pipeline/` without a dedicated metrics
module; this module closes that gap without altering any existing
behavior.

Every metric here is recorded by `pipeline.py`'s `DataPipeline` at the
point it already independently knows the fact — this module never
recomputes anything (e.g. it does not re-derive `duplicate_tick_count`
from `TickIngestor`'s own counters; `DataPipeline` records each event
once, at the source, matching the "compute once, share the result"
discipline `ADR-013` §2 already establishes for aggregation).

`latency` is recorded only when `DataQualityReport.latency_seconds` is
not `None` — Phase 1 has no live broker feed adapter yet, so this metric
has zero recordings today; the plumbing exists so a real feed can supply
it later without a second change here (see `quality.py`'s own docstring
on why `latency_seconds` is honestly `None` in Phase 1).
"""

from __future__ import annotations

from typing import List


class DataPipelineMetrics:
    def __init__(self) -> None:
        self._latencies_seconds: List[float] = []
        self._gap_count = 0
        self._gap_repair_count = 0
        self._duplicate_tick_count = 0
        self._dropped_tick_count = 0
        self._out_of_order_tick_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._replay_ready_count = 0
        self._replay_checked_count = 0

    def record_latency(self, seconds: float) -> None:
        self._latencies_seconds.append(seconds)

    def record_gap_detected(self, missing_bar_count: int) -> None:
        self._gap_count += missing_bar_count

    def record_gap_repaired(self, count: int = 1) -> None:
        self._gap_repair_count += count

    def record_duplicate_tick(self) -> None:
        self._duplicate_tick_count += 1

    def record_dropped_tick(self) -> None:
        self._dropped_tick_count += 1

    def record_out_of_order_tick(self) -> None:
        self._out_of_order_tick_count += 1

    def record_cache_access(self, hit: bool) -> None:
        if hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    def record_replay_readiness(self, ready: bool) -> None:
        self._replay_checked_count += 1
        if ready:
            self._replay_ready_count += 1

    @property
    def average_latency_seconds(self) -> float:
        if not self._latencies_seconds:
            return 0.0
        return sum(self._latencies_seconds) / len(self._latencies_seconds)

    @property
    def gap_count(self) -> int:
        return self._gap_count

    @property
    def gap_repair_count(self) -> int:
        return self._gap_repair_count

    @property
    def duplicate_tick_count(self) -> int:
        return self._duplicate_tick_count

    @property
    def dropped_tick_count(self) -> int:
        return self._dropped_tick_count

    @property
    def out_of_order_tick_count(self) -> int:
        return self._out_of_order_tick_count

    @property
    def cache_hit_ratio(self) -> float:
        total = self._cache_hits + self._cache_misses
        if total == 0:
            return 0.0
        return self._cache_hits / total

    @property
    def replay_readiness_ratio(self) -> float:
        if self._replay_checked_count == 0:
            return 0.0
        return self._replay_ready_count / self._replay_checked_count
