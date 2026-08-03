"""Watchdog-only metrics tests (ADR-011 §13) — export-only, additive,
zero effect on returned outputs."""

from __future__ import annotations

import unittest

from phantom_pipeline.watchdog.metrics import WatchdogMetrics
from phantom_pipeline.watchdog.models import HealthState, RecoveryOutcome


class TestWatchdogMetrics(unittest.TestCase):
    def test_state_counts_increment(self):
        metrics = WatchdogMetrics()
        metrics.record_component_state("scanner", HealthState.HEALTHY)
        metrics.record_component_state("scanner", HealthState.CRITICAL)
        self.assertEqual(metrics.state_counts.get("HEALTHY"), 1)
        self.assertEqual(metrics.state_counts.get("CRITICAL"), 1)

    def test_crash_count_increments_on_critical_or_offline(self):
        metrics = WatchdogMetrics()
        metrics.record_component_state("scanner", HealthState.CRITICAL)
        metrics.record_component_state("mt5_bridge", HealthState.OFFLINE)
        metrics.record_component_state("scoring_engine", HealthState.HEALTHY)
        self.assertEqual(metrics.crash_count, 2)

    def test_recovery_success_rate(self):
        metrics = WatchdogMetrics()
        metrics.record_recovery_attempt("scanner", RecoveryOutcome.SUCCEEDED)
        metrics.record_recovery_attempt("scanner", RecoveryOutcome.FAILED)
        self.assertEqual(metrics.recovery_success_rate, 0.5)
        self.assertEqual(metrics.restart_count, 2)

    def test_dependency_failure_counts(self):
        metrics = WatchdogMetrics()
        metrics.record_dependency_failure("mt5_broker_feed")
        metrics.record_dependency_failure("mt5_broker_feed")
        self.assertEqual(metrics.dependency_failure_counts.get("mt5_broker_feed"), 2)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = WatchdogMetrics()
        metrics.record_component_state("scanner", HealthState.HEALTHY)
        snapshot = metrics.state_counts
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.state_counts)

    def test_empty_metrics_have_zero_defaults(self):
        metrics = WatchdogMetrics()
        self.assertEqual(metrics.average_heartbeat_latency_seconds, 0.0)
        self.assertEqual(metrics.average_recovery_time_seconds, 0.0)
        self.assertEqual(metrics.recovery_success_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
