"""Unit category: the pure helper functions (heartbeat state
derivation, snapshot freshness, degradation-level derivation, resource
sampling failure isolation)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.reliability.degradation import derive_degradation_level
from phantom.reliability.heartbeat import derive_heartbeat_state
from phantom.reliability.models import ComponentHealth, DegradationLevel, HealthState, QueueDepth, ResourceUsage
from phantom.reliability.resource_monitor import sample_resource_usage
from phantom.reliability.snapshot_freshness import is_snapshot_fresh
from tests.phantom.reliability._fixtures import T0, make_config


class TestHeartbeatState(unittest.TestCase):
    def test_no_heartbeat_ever_is_unknown(self):
        self.assertEqual(derive_heartbeat_state(None, T0, make_config()), HealthState.UNKNOWN)

    def test_recent_heartbeat_is_healthy(self):
        state = derive_heartbeat_state(T0, T0 + timedelta(seconds=1), make_config())
        self.assertEqual(state, HealthState.HEALTHY)

    def test_moderately_stale_heartbeat_is_degraded(self):
        config = make_config(heartbeat_healthy_interval_seconds=5.0, heartbeat_degraded_interval_seconds=15.0)
        state = derive_heartbeat_state(T0, T0 + timedelta(seconds=10), config)
        self.assertEqual(state, HealthState.DEGRADED)

    def test_very_stale_heartbeat_is_unhealthy(self):
        config = make_config(heartbeat_degraded_interval_seconds=15.0, heartbeat_grace_period_seconds=30.0)
        state = derive_heartbeat_state(T0, T0 + timedelta(seconds=20), config)
        self.assertEqual(state, HealthState.UNHEALTHY)

    def test_beyond_grace_period_is_unknown_never_healthy(self):
        config = make_config(heartbeat_grace_period_seconds=30.0)
        state = derive_heartbeat_state(T0, T0 + timedelta(seconds=60), config)
        self.assertEqual(state, HealthState.UNKNOWN)

    def test_future_timestamp_is_never_trusted(self):
        state = derive_heartbeat_state(T0 + timedelta(seconds=10), T0, make_config())
        self.assertEqual(state, HealthState.UNKNOWN)


class TestSnapshotFreshness(unittest.TestCase):
    def test_fresh_snapshot_passes(self):
        config = make_config(snapshot_freshness_threshold_seconds=5.0)
        self.assertTrue(is_snapshot_fresh(T0, T0 + timedelta(seconds=1), config))

    def test_stale_snapshot_fails(self):
        config = make_config(snapshot_freshness_threshold_seconds=5.0)
        self.assertFalse(is_snapshot_fresh(T0, T0 + timedelta(seconds=10), config))

    def test_future_snapshot_fails(self):
        config = make_config()
        self.assertFalse(is_snapshot_fresh(T0 + timedelta(seconds=10), T0, config))


class TestResourceSampling(unittest.TestCase):
    def test_a_failing_sampler_degrades_only_that_field(self):
        def failing_cpu():
            raise RuntimeError("boom")

        def ok_memory():
            return 42.0

        usage = sample_resource_usage(T0, cpu_sampler=failing_cpu, memory_sampler=ok_memory)
        self.assertIsNone(usage.cpu_percent)
        self.assertEqual(usage.memory_percent, 42.0)

    def test_both_samplers_failing_produces_a_valid_all_none_reading(self):
        def failing():
            raise RuntimeError("boom")

        usage = sample_resource_usage(T0, cpu_sampler=failing, memory_sampler=failing)
        self.assertIsNone(usage.cpu_percent)
        self.assertIsNone(usage.memory_percent)


class TestDegradationLevel(unittest.TestCase):
    def test_all_healthy_no_resources_is_normal(self):
        health = (ComponentHealth("evidence_engine", HealthState.HEALTHY, T0, "ok"),)
        level, reasons = derive_degradation_level(health, None, (), make_config())
        self.assertEqual(level, DegradationLevel.NORMAL)
        self.assertEqual(reasons, ())

    def test_any_unknown_component_is_halted(self):
        health = (ComponentHealth("evidence_engine", HealthState.UNKNOWN, None, "no heartbeat"),)
        level, reasons = derive_degradation_level(health, None, (), make_config())
        self.assertEqual(level, DegradationLevel.HALTED)
        self.assertTrue(reasons)

    def test_unhealthy_component_is_critical(self):
        health = (ComponentHealth("evidence_engine", HealthState.UNHEALTHY, T0, "stale"),)
        level, _ = derive_degradation_level(health, None, (), make_config())
        self.assertEqual(level, DegradationLevel.CRITICAL)

    def test_degraded_component_is_degraded(self):
        health = (ComponentHealth("evidence_engine", HealthState.DEGRADED, T0, "aging"),)
        level, _ = derive_degradation_level(health, None, (), make_config())
        self.assertEqual(level, DegradationLevel.DEGRADED)

    def test_high_cpu_escalates_to_critical(self):
        config = make_config(cpu_critical_threshold_pct=90.0)
        usage = ResourceUsage(cpu_percent=95.0, memory_percent=None, sampled_at=T0)
        level, reasons = derive_degradation_level((), usage, (), config)
        self.assertEqual(level, DegradationLevel.CRITICAL)
        self.assertTrue(reasons)

    def test_moderate_cpu_escalates_to_degraded(self):
        config = make_config(cpu_degraded_threshold_pct=70.0, cpu_critical_threshold_pct=90.0)
        usage = ResourceUsage(cpu_percent=75.0, memory_percent=None, sampled_at=T0)
        level, _ = derive_degradation_level((), usage, (), config)
        self.assertEqual(level, DegradationLevel.DEGRADED)

    def test_critical_queue_depth_escalates_to_critical(self):
        config = make_config(queue_critical_depth=500)
        queue = QueueDepth(name="bridge_commands", depth=600, reported_at=T0)
        level, _ = derive_degradation_level((), None, (queue,), config)
        self.assertEqual(level, DegradationLevel.CRITICAL)


if __name__ == "__main__":
    unittest.main()
