"""`PrometheusReadPort`/`FakePrometheusReadPort` tests — the fake never
touches any real process, and the ABC itself exposes read methods only
(ADR-012 §4, §9's structural read-only guarantee, and the "permission
verification" requirement of §10, tested here structurally)."""

from __future__ import annotations

import unittest

from phantom_pipeline.dashboard.models import AlertView, ComponentStatus, SystemMetric
from phantom_pipeline.dashboard.prometheus_port import FakePrometheusReadPort, PrometheusReadPort
from tests.phantom_pipeline.dashboard._fixtures import T0

_FORBIDDEN_VERB_PREFIXES = ("set_", "write_", "clear_", "delete_", "update_", "execute_", "submit_", "restart_")


class TestPrometheusReadPortIsReadOnly(unittest.TestCase):
    def test_abc_has_no_write_capable_method(self):
        """Permission verification (§10): the abstract interface itself
        exposes only queries — no mutation method exists on the contract
        every real Prometheus client must implement."""
        abstract_methods = PrometheusReadPort.__abstractmethods__
        for name in abstract_methods:
            self.assertFalse(
                any(name.startswith(prefix) for prefix in _FORBIDDEN_VERB_PREFIXES),
                f"{name} looks like a write-capable method on a read-only port",
            )

    def test_abc_methods_are_exactly_the_three_reads(self):
        self.assertEqual(set(PrometheusReadPort.__abstractmethods__), {"component_statuses", "system_metrics", "alerts"})


class TestFakePrometheusReadPort(unittest.TestCase):
    def test_component_statuses_filters_by_name(self):
        port = FakePrometheusReadPort()
        port.set_component_status(ComponentStatus("scanner", "HEALTHY", "ok", "t1", T0))
        port.set_component_status(ComponentStatus("risk_engine", "HEALTHY", "ok", "t2", T0))
        result = port.component_statuses(["scanner"])
        self.assertEqual([c.component for c in result], ["scanner"])

    def test_component_statuses_returns_all_when_no_filter(self):
        port = FakePrometheusReadPort()
        port.set_component_status(ComponentStatus("scanner", "HEALTHY", "ok", "t1", T0))
        port.set_component_status(ComponentStatus("risk_engine", "HEALTHY", "ok", "t2", T0))
        result = port.component_statuses()
        self.assertEqual({c.component for c in result}, {"scanner", "risk_engine"})

    def test_unknown_component_in_filter_is_silently_omitted(self):
        port = FakePrometheusReadPort()
        port.set_component_status(ComponentStatus("scanner", "HEALTHY", "ok", "t1", T0))
        result = port.component_statuses(["scanner", "never_registered"])
        self.assertEqual([c.component for c in result], ["scanner"])

    def test_system_metrics_and_alerts_scriptable(self):
        port = FakePrometheusReadPort()
        port.set_system_metric(SystemMetric("cpu_pct", 10.0, "%", T0))
        port.set_alerts([AlertView("mt5_bridge", "CRITICAL", "CRITICAL", "down", 1, "t3", T0)])
        self.assertEqual(len(port.system_metrics()), 1)
        self.assertEqual(len(port.alerts()), 1)

    def test_empty_port_returns_empty_tuples(self):
        port = FakePrometheusReadPort()
        self.assertEqual(port.component_statuses(), ())
        self.assertEqual(port.system_metrics(), ())
        self.assertEqual(port.alerts(), ())


if __name__ == "__main__":
    unittest.main()
