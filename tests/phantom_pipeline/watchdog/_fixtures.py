"""Shared test-only fixtures for the Watchdog test suite."""

from __future__ import annotations

from datetime import datetime, timezone

from phantom_pipeline.watchdog import ComponentKind, ComponentSignal, WatchdogConfig

T0 = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def make_signal(component: str = "scanner", **overrides) -> ComponentSignal:
    kwargs = dict(component=component, kind=ComponentKind.PIPELINE_STAGE, reported_state=None, detail="")
    kwargs.update(overrides)
    return ComponentSignal(**kwargs)


def make_config(**overrides) -> WatchdogConfig:
    kwargs = dict(
        default_heartbeat_interval_seconds=30.0,
        warning_missed_threshold=2,
        critical_missed_threshold=5,
        heartbeat_max_age_multiplier=10.0,
        recovery_max_attempts=3,
        recovery_window_seconds=300.0,
        recovery_backoff_seconds=0.0,
        alert_escalation_duration_seconds=600.0,
        alert_dedup_window_seconds=300.0,
    )
    kwargs.update(overrides)
    return WatchdogConfig(**kwargs)
