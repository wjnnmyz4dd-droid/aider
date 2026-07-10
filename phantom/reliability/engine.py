"""`ReliabilityEngine` -- the System Reliability Engine's orchestrator
(Phase 3B, ADR-032).

Unlike the six pure, per-call trading engines this session built,
this engine is a genuinely stateful observer (heartbeats, rolling
cycle history, last resource sample) -- the same discipline `ADR-011`'s
own Watchdog already established for a cross-cutting health monitor.
Thread safety is provided by one internal lock guarding all mutable
state; every public method is safe to call concurrently.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

from phantom.runtime.models import CycleOutcome, CycleReport

from .config import ReliabilityConfig
from .degradation import derive_degradation_level
from .heartbeat import HeartbeatStore, derive_heartbeat_state
from .logging_sink import log_health_snapshot
from .metrics import ReliabilityMetrics
from .models import ComponentHealth, CycleOutcomeStats, DegradationLevel, HealthState, QueueDepth, RecoveryOutcome, ResourceUsage, SystemHealthSnapshot
from .recovery import attempt_recovery as _attempt_recovery
from .resource_monitor import CpuSampler, MemorySampler, default_cpu_sampler, default_memory_sampler, sample_resource_usage
from .snapshot_freshness import is_snapshot_fresh


class _CycleAccumulator:
    def __init__(self, window: int) -> None:
        self.durations: Deque[float] = deque(maxlen=window)
        self.outcomes: Deque[CycleOutcome] = deque(maxlen=window)
        self.total_cycles = 0
        self.failed_cycles = 0
        self.last_outcome: Optional[CycleOutcome] = None
        self.last_seen_at: Optional[datetime] = None


class ReliabilityEngine:
    def __init__(
        self,
        config: ReliabilityConfig,
        cpu_sampler: CpuSampler = default_cpu_sampler,
        memory_sampler: MemorySampler = default_memory_sampler,
        metrics: Optional[ReliabilityMetrics] = None,
    ) -> None:
        self.config = config
        self.cpu_sampler = cpu_sampler
        self.memory_sampler = memory_sampler
        self.metrics = metrics
        self._lock = threading.Lock()
        self._heartbeats = HeartbeatStore()
        self._cycle_stats: Dict[str, _CycleAccumulator] = {}
        self._queue_depths: Dict[str, QueueDepth] = {}
        self._resource_usage: Optional[ResourceUsage] = None

    def report_heartbeat(self, component: str, now: datetime) -> None:
        self._heartbeats.record(component, now)
        if self.metrics is not None:
            self.metrics.record_heartbeat()

    def record_cycle(self, cycle_report: CycleReport) -> None:
        with self._lock:
            for record in cycle_report.records:
                accumulator = self._cycle_stats.setdefault(record.pair, _CycleAccumulator(self.config.cycle_history_window))
                accumulator.durations.append(record.duration_ms)
                accumulator.outcomes.append(record.outcome)
                accumulator.total_cycles += 1
                if record.outcome == CycleOutcome.FAILED:
                    accumulator.failed_cycles += 1
                accumulator.last_outcome = record.outcome
                accumulator.last_seen_at = record.ended_at
        if self.metrics is not None:
            self.metrics.record_cycle_report(len(cycle_report.records))

    def report_resource_usage(self, now: datetime) -> ResourceUsage:
        usage = sample_resource_usage(now, self.cpu_sampler, self.memory_sampler)
        with self._lock:
            self._resource_usage = usage
        return usage

    def report_queue_depth(self, name: str, depth: int, now: datetime) -> None:
        with self._lock:
            self._queue_depths[name] = QueueDepth(name=name, depth=depth, reported_at=now)

    def is_snapshot_fresh(self, generated_at: datetime, now: datetime) -> bool:
        return is_snapshot_fresh(generated_at, now, self.config)

    def evaluate_health(self, now: datetime) -> SystemHealthSnapshot:
        with self._lock:
            components = self._heartbeats.known_components()
            component_health = tuple(
                ComponentHealth(
                    component=component,
                    state=(state := derive_heartbeat_state(self._heartbeats.last_seen_at(component), now, self.config)),
                    last_heartbeat_at=self._heartbeats.last_seen_at(component),
                    reason=f"heartbeat age-derived state: {state.value}",
                )
                for component in components
            )
            cycle_stats = tuple(
                CycleOutcomeStats(
                    pair=pair,
                    total_cycles=acc.total_cycles,
                    failed_cycles=acc.failed_cycles,
                    average_duration_ms=(sum(acc.durations) / len(acc.durations)) if acc.durations else 0.0,
                    last_outcome=acc.last_outcome,
                    last_seen_at=acc.last_seen_at,
                )
                for pair, acc in sorted(self._cycle_stats.items())
            )
            # Windowed failure rate (over `cycle_history_window`'s most
            # recent outcomes), never the lifetime cumulative rate --
            # so a pair that recovers after a run of failures actually
            # recovers (a repeated-failures scenario must be able to
            # clear, ADR-032 SS7's own recovery-test list).
            windowed_failure_rates = {
                pair: (sum(1 for o in acc.outcomes if o == CycleOutcome.FAILED) / len(acc.outcomes)) if acc.outcomes else 0.0
                for pair, acc in self._cycle_stats.items()
            }
            queue_depths = tuple(sorted(self._queue_depths.values(), key=lambda q: q.name))
            resource_usage = self._resource_usage

        level, reasons = derive_degradation_level(component_health, resource_usage, queue_depths, self.config)

        failure_rate_reasons: List[str] = []
        for pair, failure_rate in sorted(windowed_failure_rates.items()):
            if failure_rate >= self.config.cycle_failure_rate_critical:
                failure_rate_reasons.append(f"pair {pair!r} failure rate {failure_rate:.0%} >= critical threshold")
        if failure_rate_reasons and level not in (DegradationLevel.HALTED,):
            level = DegradationLevel.CRITICAL
            reasons = reasons + tuple(failure_rate_reasons)

        snapshot = SystemHealthSnapshot(
            generated_at=now, degradation_level=level, component_health=component_health,
            resource_usage=resource_usage, queue_depths=queue_depths, cycle_stats=cycle_stats, reasons=reasons,
        )
        log_health_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation(level)
        return snapshot

    def is_halted(self, now: datetime) -> bool:
        return self.evaluate_health(now).degradation_level == DegradationLevel.HALTED

    def attempt_recovery(self, component: str, now: datetime) -> RecoveryOutcome:
        outcome = _attempt_recovery(component, now)
        if self.metrics is not None:
            self.metrics.record_recovery_attempt(outcome.succeeded)
        return outcome


__all__ = ["ReliabilityEngine"]
