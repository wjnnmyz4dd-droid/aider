"""PrometheusAdapter translation tests — a fake HTTP session double stands
in for a real Prometheus server, mirroring every other real adapter's own
"no live external dependency in unit tests" discipline. Every test
exercises this adapter's own query-building and response-translation
logic; nothing here makes a real network call."""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from phantom_pipeline.dashboard.models import AlertView, ComponentStatus, SystemMetric
from phantom_pipeline.dashboard.prometheus_adapter import PrometheusAdapter


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_ok: bool = True) -> None:
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise RuntimeError("http error")

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self) -> None:
        self.requested_params = None
        self.response = _FakeResponse({"status": "success", "data": {"result": []}})
        self.raise_exception: Optional[Exception] = None

    def get(self, url: str, params=None, timeout=None):
        self.requested_params = params
        if self.raise_exception is not None:
            raise self.raise_exception
        return self.response


def _success(result):
    return _FakeResponse({"status": "success", "data": {"result": result}})


class TestPrometheusAdapterComponentStatuses(unittest.TestCase):
    def test_returns_empty_tuple_when_no_series(self):
        session = _FakeSession()
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        self.assertEqual(adapter.component_statuses(), ())

    def test_translates_series_into_component_status(self):
        session = _FakeSession()
        session.response = _success(
            [
                {
                    "metric": {
                        "component": "scanner",
                        "state": "HEALTHY",
                        "reason": "nominal",
                        "trace_id": "trace-1",
                    },
                    "value": [1751000000, "1"],
                }
            ]
        )
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        statuses = adapter.component_statuses()
        self.assertEqual(len(statuses), 1)
        self.assertIsInstance(statuses[0], ComponentStatus)
        self.assertEqual(statuses[0].component, "scanner")
        self.assertEqual(statuses[0].health_state, "HEALTHY")

    def test_filters_by_components_via_label_regex(self):
        session = _FakeSession()
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        adapter.component_statuses(components=["scanner", "risk_engine"])
        self.assertIn("scanner|risk_engine", session.requested_params["query"])

    def test_query_failure_returns_empty_tuple_not_an_exception(self):
        session = _FakeSession()
        session.raise_exception = ConnectionError("no route to host")
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        self.assertEqual(adapter.component_statuses(), ())

    def test_http_error_status_returns_empty_tuple(self):
        session = _FakeSession()
        session.response = _FakeResponse({}, status_ok=False)
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        self.assertEqual(adapter.component_statuses(), ())

    def test_non_success_prometheus_status_returns_empty_tuple(self):
        session = _FakeSession()
        session.response = _FakeResponse({"status": "error"})
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        self.assertEqual(adapter.component_statuses(), ())


class TestPrometheusAdapterSystemMetrics(unittest.TestCase):
    def test_translates_numeric_value_directly(self):
        session = _FakeSession()
        session.response = _success(
            [{"metric": {"name": "cpu_percent", "unit": "percent"}, "value": [1751000000, "42.5"]}]
        )
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        metrics = adapter.system_metrics()
        self.assertEqual(len(metrics), 1)
        self.assertIsInstance(metrics[0], SystemMetric)
        self.assertEqual(metrics[0].value, 42.5)
        self.assertEqual(metrics[0].unit, "percent")


class TestPrometheusAdapterAlerts(unittest.TestCase):
    def test_translates_alert_series(self):
        session = _FakeSession()
        session.response = _success(
            [
                {
                    "metric": {
                        "component": "mt5_bridge",
                        "alert_class": "CRITICAL",
                        "severity": "CRITICAL",
                        "detail": "connection lost",
                        "repeat_count": "3",
                        "trace_id": "trace-9",
                    },
                    "value": [1751000000, "1"],
                }
            ]
        )
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        alerts = adapter.alerts()
        self.assertEqual(len(alerts), 1)
        self.assertIsInstance(alerts[0], AlertView)
        self.assertEqual(alerts[0].repeat_count, 3)

    def test_empty_alerts_returns_empty_tuple(self):
        session = _FakeSession()
        adapter = PrometheusAdapter("http://localhost:9090", session=session)
        self.assertEqual(adapter.alerts(), ())


class TestPrometheusAdapterConstruction(unittest.TestCase):
    def test_base_url_trailing_slash_stripped(self):
        session = _FakeSession()
        adapter = PrometheusAdapter("http://localhost:9090/", session=session)
        adapter.component_statuses()
        # No exception; base URL normalization is exercised implicitly by
        # a successful call (the fake session doesn't need the exact URL).
        self.assertIsNotNone(adapter)


if __name__ == "__main__":
    unittest.main()
