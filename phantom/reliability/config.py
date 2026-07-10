"""Configuration for the System Reliability Engine (Phase 3B, ADR-032)."""

from __future__ import annotations

from dataclasses import dataclass

RELIABILITY_ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ReliabilityConfig:
    # Heartbeat staleness (ADR-032 SS2 item 2).
    heartbeat_healthy_interval_seconds: float = 5.0
    heartbeat_degraded_interval_seconds: float = 15.0
    heartbeat_grace_period_seconds: float = 30.0  # beyond this: UNKNOWN, never treated as healthy

    # Snapshot freshness (ADR-032 SS2 item 4).
    snapshot_freshness_threshold_seconds: float = 5.0

    # Resource thresholds -- degradation level derivation (ADR-032 SS2 item 11).
    cpu_degraded_threshold_pct: float = 70.0
    cpu_critical_threshold_pct: float = 90.0
    memory_degraded_threshold_pct: float = 75.0
    memory_critical_threshold_pct: float = 90.0

    # Queue depth thresholds.
    queue_degraded_depth: int = 100
    queue_critical_depth: int = 500

    # Cycle failure-rate thresholds (rolling window, ADR-032 SS2 item 5).
    cycle_history_window: int = 100
    cycle_failure_rate_degraded: float = 0.10
    cycle_failure_rate_critical: float = 0.35

    # How many consecutive UNHEALTHY components before the whole system is CRITICAL.
    unhealthy_components_for_critical: int = 1
    unknown_components_for_halted: int = 1


__all__ = ["RELIABILITY_ENGINE_VERSION", "ReliabilityConfig"]
