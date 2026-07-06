"""ProductionMonitoring tests — injected samplers, per-field fail-closed
degradation on sampler failure, threshold-breach evaluation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.deployment.monitoring import MonitoringThresholds, ProductionMonitoring

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


class TestSample(unittest.TestCase):
    def test_uses_injected_samplers(self):
        monitoring = ProductionMonitoring(
            cpu_sampler=lambda: 42.0,
            memory_sampler=lambda: 55.0,
            disk_sampler=lambda: 60.0,
            network_latency_sampler=lambda: 12.5,
            mt5_connection_checker=lambda: True,
            python_process_health_checker=lambda: True,
            dashboard_health_checker=lambda: True,
        )
        snapshot = monitoring.sample(T0)

        self.assertEqual(snapshot.resource.cpu_percent, 42.0)
        self.assertEqual(snapshot.resource.memory_percent, 55.0)
        self.assertEqual(snapshot.resource.disk_percent, 60.0)
        self.assertEqual(snapshot.resource.network_latency_ms, 12.5)
        self.assertTrue(snapshot.mt5_connection_healthy)
        self.assertTrue(snapshot.python_process_healthy)
        self.assertTrue(snapshot.dashboard_healthy)

    def test_a_raising_sampler_degrades_only_its_own_field(self):
        def _raises():
            raise RuntimeError("sensor unavailable")

        monitoring = ProductionMonitoring(
            cpu_sampler=_raises,
            memory_sampler=lambda: 10.0,
            mt5_connection_checker=_raises,
        )
        snapshot = monitoring.sample(T0)

        self.assertIsNone(snapshot.resource.cpu_percent)
        self.assertEqual(snapshot.resource.memory_percent, 10.0)
        self.assertIsNone(snapshot.mt5_connection_healthy)


class TestEvaluate(unittest.TestCase):
    def test_reports_breaches_over_threshold(self):
        monitoring = ProductionMonitoring(cpu_sampler=lambda: 99.0, memory_sampler=lambda: 10.0)
        snapshot = monitoring.sample(T0)

        breaches = monitoring.evaluate(snapshot, MonitoringThresholds(cpu_percent_max=85.0))

        self.assertTrue(any("CPU" in b for b in breaches))

    def test_no_breaches_when_within_thresholds(self):
        monitoring = ProductionMonitoring(
            cpu_sampler=lambda: 10.0, memory_sampler=lambda: 10.0,
            disk_sampler=lambda: 10.0, network_latency_sampler=lambda: 10.0,
        )
        snapshot = monitoring.sample(T0)

        breaches = monitoring.evaluate(snapshot)

        self.assertEqual(breaches, ())

    def test_none_readings_never_produce_a_breach(self):
        monitoring = ProductionMonitoring(cpu_sampler=lambda: None)
        snapshot = monitoring.sample(T0)

        breaches = monitoring.evaluate(snapshot)

        self.assertEqual(breaches, ())


if __name__ == "__main__":
    unittest.main()
