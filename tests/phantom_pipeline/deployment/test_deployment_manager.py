"""ProductionDeploymentManager tests — dependency-ordered start/stop,
pre-launch dependency verification, health verification, graceful reverse
shutdown order."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.deployment.deployment_manager import ProductionDeploymentManager
from phantom_pipeline.deployment.models import ServiceDefinition, ServiceState

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _service(name, order_log, depends_on=(), start_ok=True, health_ok=True, stop_ok=True):
    def start():
        order_log.append(("start", name))
        return start_ok

    def stop():
        order_log.append(("stop", name))
        return stop_ok

    def health_check():
        return health_ok

    return ServiceDefinition(name=name, start=start, stop=stop, health_check=health_check, depends_on=depends_on)


class TestStartupOrder(unittest.TestCase):
    def test_dependencies_start_before_dependents(self):
        order_log = []
        data_feed = _service("data_feed", order_log)
        mt5 = _service("mt5", order_log, depends_on=("data_feed",))
        dashboard = _service("dashboard", order_log, depends_on=("mt5",))
        # deliberately out-of-order registration
        manager = ProductionDeploymentManager([dashboard, mt5, data_feed])

        result = manager.start_all(T0)

        self.assertTrue(result.all_started)
        started_order = [name for action, name in order_log if action == "start"]
        self.assertEqual(started_order, ["data_feed", "mt5", "dashboard"])


class TestShutdownOrder(unittest.TestCase):
    def test_shutdown_is_reverse_of_startup_order(self):
        order_log = []
        data_feed = _service("data_feed", order_log)
        mt5 = _service("mt5", order_log, depends_on=("data_feed",))
        manager = ProductionDeploymentManager([data_feed, mt5])

        manager.stop_all(T0)

        stopped_order = [name for action, name in order_log if action == "stop"]
        self.assertEqual(stopped_order, ["mt5", "data_feed"])


class TestDependencyVerification(unittest.TestCase):
    def test_failed_dependency_check_aborts_startup_and_starts_nothing(self):
        order_log = []
        data_feed = _service("data_feed", order_log)
        manager = ProductionDeploymentManager([data_feed], dependency_checks=[lambda: "disk full"])

        result = manager.start_all(T0)

        self.assertFalse(result.all_started)
        self.assertEqual(result.aborted_reason, "disk full")
        self.assertEqual(result.statuses, ())
        self.assertEqual(order_log, [])

    def test_passing_dependency_checks_allow_startup(self):
        order_log = []
        data_feed = _service("data_feed", order_log)
        manager = ProductionDeploymentManager([data_feed], dependency_checks=[lambda: None])

        result = manager.start_all(T0)

        self.assertTrue(result.all_started)


class TestStartupFailureHandling(unittest.TestCase):
    def test_a_failed_start_aborts_remaining_startups(self):
        order_log = []
        data_feed = _service("data_feed", order_log, start_ok=False)
        mt5 = _service("mt5", order_log, depends_on=("data_feed",))
        manager = ProductionDeploymentManager([data_feed, mt5])

        result = manager.start_all(T0)

        self.assertFalse(result.all_started)
        self.assertEqual(len(result.statuses), 1)
        self.assertEqual(result.statuses[0].state, ServiceState.CRASHED)
        self.assertEqual([name for _, name in order_log], ["data_feed"])

    def test_an_unhealthy_started_service_marks_startup_as_not_fully_started(self):
        order_log = []
        data_feed = _service("data_feed", order_log, health_ok=False)
        manager = ProductionDeploymentManager([data_feed])

        result = manager.start_all(T0)

        self.assertFalse(result.all_started)
        self.assertEqual(result.statuses[0].state, ServiceState.DEGRADED)


class TestHealthCheckAll(unittest.TestCase):
    def test_reports_health_for_every_service(self):
        order_log = []
        healthy = _service("healthy", order_log, health_ok=True)
        unhealthy = _service("unhealthy", order_log, health_ok=False)
        manager = ProductionDeploymentManager([healthy, unhealthy])

        statuses = {s.name: s.state for s in manager.health_check_all(T0)}

        self.assertEqual(statuses["healthy"], ServiceState.RUNNING)
        self.assertEqual(statuses["unhealthy"], ServiceState.DEGRADED)


class TestCircularDependencyDetection(unittest.TestCase):
    def test_raises_on_circular_dependency(self):
        order_log = []
        a = _service("a", order_log, depends_on=("b",))
        b = _service("b", order_log, depends_on=("a",))
        with self.assertRaises(ValueError):
            ProductionDeploymentManager([a, b])


if __name__ == "__main__":
    unittest.main()
