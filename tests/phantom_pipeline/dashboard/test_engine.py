"""DashboardEngine tests — covers ADR-012 §10's Testing list: view
consistency, metric consistency, trace consistency, read-only
verification, permission verification (structural)."""

from __future__ import annotations

import unittest

from phantom_pipeline.dashboard.config import DashboardConfig
from phantom_pipeline.dashboard.engine import DashboardEngine
from phantom_pipeline.dashboard.metrics import DashboardMetrics
from phantom_pipeline.dashboard.models import AlertView, ComponentStatus, SystemMetric, ViewName
from phantom_pipeline.dashboard.prometheus_port import FakePrometheusReadPort
from tests.phantom_pipeline.dashboard._fixtures import T0, make_performance_statistics, make_trade_record


def _engine_with_data():
    port = FakePrometheusReadPort()
    for component in ("scanner", "strategy_engine", "scoring_engine", "risk_engine", "compliance_engine",
                      "execution_validator", "mt5_bridge", "position_manager", "analytics", "watchdog",
                      "cpu", "memory", "disk", "network", "vps"):
        port.set_component_status(ComponentStatus(component, "HEALTHY", "ok", f"trace-{component}", T0))
    port.set_system_metric(SystemMetric("cpu_pct", 12.5, "%", T0))
    port.set_system_metric(SystemMetric("recovery_time_seconds", 3.0, "s", T0))
    port.set_alerts([AlertView("mt5_bridge", "CRITICAL", "CRITICAL", "connection lost", 1, "health-trace-1", T0)])
    metrics = DashboardMetrics()
    engine = DashboardEngine(port, metrics=metrics)
    return engine, port, metrics


class TestViewConsistency(unittest.TestCase):
    """Each of the ten views renders only data attributable to §4's two
    sources; no view silently reaches a pipeline stage directly."""

    def test_trading_view_only_shows_its_own_configured_components(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_trading_view(T0)
        self.assertEqual({c.component for c in view.component_statuses}, {"scanner", "strategy_engine", "scoring_engine"})

    def test_risk_view_only_shows_risk_engine(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_risk_view(T0)
        self.assertEqual({c.component for c in view.component_statuses}, {"risk_engine"})

    def test_compliance_view_only_shows_compliance_engine(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_compliance_view(T0)
        self.assertEqual({c.component for c in view.component_statuses}, {"compliance_engine"})

    def test_execution_view_only_shows_execution_validator_and_mt5_bridge(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_execution_view(T0)
        self.assertEqual({c.component for c in view.component_statuses}, {"execution_validator", "mt5_bridge"})

    def test_infrastructure_view_shows_infra_components_and_system_metrics(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_infrastructure_view(T0)
        self.assertIn("watchdog", {c.component for c in view.component_statuses})
        self.assertTrue(len(view.system_metrics) > 0)

    def test_overview_view_shows_all_components(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_overview_view(T0)
        self.assertEqual(len(view.component_statuses), 15)

    def test_alerts_view_shows_alerts_and_no_components(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_alerts_view(T0)
        self.assertEqual(len(view.alerts), 1)
        self.assertEqual(view.component_statuses, ())

    def test_analytics_view_shows_no_components_only_analytics_data(self):
        engine, port, _ = _engine_with_data()
        records = (make_trade_record("t1"),)
        performance = make_performance_statistics()
        view = engine.build_analytics_view(T0, records=records, performance=performance)
        self.assertEqual(view.component_statuses, ())
        self.assertEqual(view.trade_records, records)
        self.assertEqual(view.performance, performance)

    def test_audit_view_shows_only_trade_records(self):
        engine, port, _ = _engine_with_data()
        records = (make_trade_record("t1"), make_trade_record("t2"))
        view = engine.build_audit_view(T0, records=records)
        self.assertEqual(view.trade_records, records)
        self.assertEqual(view.component_statuses, ())
        self.assertEqual(view.alerts, ())

    def test_research_view_is_empty_since_adr_016_019_not_started(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_research_view(T0)
        self.assertEqual(view.component_statuses, ())
        self.assertEqual(view.alerts, ())
        self.assertEqual(view.trade_records, ())
        self.assertIsNone(view.performance)

    def test_no_view_reaches_a_pipeline_stage_directly(self):
        """Every view's data originates only from the port or explicit
        Analytics params passed by the caller — never a direct import of
        a pipeline stage's engine."""
        import phantom_pipeline.dashboard.engine as engine_module
        with open(engine_module.__file__) as f:
            source = f.read()
        for forbidden in ("scanner.engine", "risk_engine.engine", "compliance_engine.engine",
                          "execution_validator.engine", "mt5_bridge.engine", "position_manager.engine",
                          "watchdog.engine", "strategy_engine.engine", "scoring_engine.engine"):
            self.assertNotIn(forbidden, source)


class TestMetricConsistency(unittest.TestCase):
    """Every displayed metric exactly matches its source value, with no
    Dashboard-side recomputation."""

    def test_component_status_values_pass_through_unchanged(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_trading_view(T0)
        scanner_status = next(c for c in view.component_statuses if c.component == "scanner")
        self.assertEqual(scanner_status.health_state, "HEALTHY")
        self.assertEqual(scanner_status.reason, "ok")

    def test_system_metric_values_pass_through_unchanged(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_infrastructure_view(T0)
        cpu_metric = next(m for m in view.system_metrics if m.name == "cpu_pct")
        self.assertEqual(cpu_metric.value, 12.5)

    def test_performance_statistics_passed_through_unchanged(self):
        engine, port, _ = _engine_with_data()
        performance = make_performance_statistics(win_rate=0.75)
        view = engine.build_analytics_view(T0, performance=performance)
        self.assertEqual(view.performance.win_rate, 0.75)
        self.assertIs(view.performance, performance)


class TestTraceConsistency(unittest.TestCase):
    """Every displayed item's trace_id resolves to its originating chain
    (trading vs. health) via its own component field — never merged."""

    def test_component_status_trace_id_is_the_health_event_chain(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_infrastructure_view(T0)
        watchdog_status = next(c for c in view.component_statuses if c.component == "watchdog")
        self.assertEqual(watchdog_status.trace_id, "trace-watchdog")

    def test_trade_record_trace_id_is_the_trading_chain(self):
        engine, port, _ = _engine_with_data()
        record = make_trade_record("trading-trace-1")
        view = engine.build_audit_view(T0, records=(record,))
        self.assertEqual(view.trade_records[0].trace_id, "trading-trace-1")

    def test_alert_trace_id_is_the_health_event_chain(self):
        engine, port, _ = _engine_with_data()
        view = engine.build_alerts_view(T0)
        self.assertEqual(view.alerts[0].trace_id, "health-trace-1")

    def test_view_itself_carries_no_single_merged_trace_id(self):
        """View has no `trace_id` field of its own — each item inside it
        carries its own, so the two chains are never blurred together."""
        from phantom_pipeline.dashboard.models import View
        field_names = {f.name for f in __import__("dataclasses").fields(View)}
        self.assertNotIn("trace_id", field_names)


class TestReadOnlyVerification(unittest.TestCase):
    """No code path in the Dashboard issues a write to any pipeline
    stage, Watchdog's alert-management state, configuration, or MT5."""

    _FORBIDDEN_VERBS = ("execute", "submit", "restart", "clear_alert", "acknowledge", "suppress", "override", "place_order")

    def test_engine_has_no_write_capable_public_method(self):
        public_methods = [name for name in dir(DashboardEngine) if not name.startswith("_")]
        for name in public_methods:
            for verb in self._FORBIDDEN_VERBS:
                self.assertNotIn(verb, name.lower(), f"{name} looks like a write-capable method")

    def test_all_public_methods_are_view_builders(self):
        public_methods = [name for name in dir(DashboardEngine) if not name.startswith("_") and callable(getattr(DashboardEngine, name))]
        self.assertTrue(all(name.startswith("build_") for name in public_methods))


class TestDeterminismAndMetricsIntegration(unittest.TestCase):
    def test_same_inputs_produce_identical_view(self):
        engine1, _, _ = _engine_with_data()
        engine2, _, _ = _engine_with_data()
        view1 = engine1.build_overview_view(T0)
        view2 = engine2.build_overview_view(T0)
        self.assertEqual(view1.component_statuses, view2.component_statuses)

    def test_building_a_view_records_dashboard_metrics(self):
        engine, port, metrics = _engine_with_data()
        engine.build_overview_view(T0)
        engine.build_overview_view(T0)
        self.assertEqual(metrics.views_built.get("OVERVIEW"), 2)


if __name__ == "__main__":
    unittest.main()
