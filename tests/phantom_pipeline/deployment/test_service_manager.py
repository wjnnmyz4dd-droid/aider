"""WindowsServiceManager tests — auto-start after reboot, crash/hang
restart, restart-reason logging, and the hard rule that MT5 is never
restarted while a trade is actively executing."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.deployment.models import RestartReason, ServiceState
from phantom_pipeline.deployment.service_manager import MT5_SERVICE_NAME, WindowsServiceManager

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


class _FakeService:
    def __init__(self, running: bool = True, responsive: bool = True):
        self.running = running
        self.responsive = responsive
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        self.running = True
        return True

    def stop(self) -> bool:
        self.stop_calls += 1
        self.running = False
        return True

    def is_running(self) -> bool:
        return self.running

    def is_responsive(self) -> bool:
        return self.responsive


class TestEnsureStartedAfterReboot(unittest.TestCase):
    def test_starts_every_registered_service_not_already_running(self):
        manager = WindowsServiceManager()
        dashboard = _FakeService(running=False)
        manager.register_service("dashboard", dashboard.start, dashboard.stop, dashboard.is_running, dashboard.is_responsive)

        statuses = manager.ensure_started_after_reboot(T0)

        self.assertEqual(dashboard.start_calls, 1)
        self.assertEqual(statuses[0].state, ServiceState.RUNNING)

    def test_does_not_restart_an_already_running_service(self):
        manager = WindowsServiceManager()
        dashboard = _FakeService(running=True)
        manager.register_service("dashboard", dashboard.start, dashboard.stop, dashboard.is_running, dashboard.is_responsive)

        manager.ensure_started_after_reboot(T0)

        self.assertEqual(dashboard.start_calls, 0)


class TestCrashRestart(unittest.TestCase):
    def test_restarts_a_crashed_service_and_logs_the_reason(self):
        manager = WindowsServiceManager()
        watchdog = _FakeService(running=False)
        manager.register_service("watchdog", watchdog.start, watchdog.stop, watchdog.is_running, watchdog.is_responsive)

        records = manager.check_and_restart_crashed(T0)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].reason, RestartReason.CRASH_DETECTED)
        self.assertTrue(records[0].succeeded)
        self.assertEqual(watchdog.start_calls, 1)
        self.assertIn(records[0], manager.restart_history)

    def test_healthy_service_is_never_restarted(self):
        manager = WindowsServiceManager()
        dashboard = _FakeService(running=True)
        manager.register_service("dashboard", dashboard.start, dashboard.stop, dashboard.is_running, dashboard.is_responsive)

        records = manager.check_and_restart_crashed(T0)

        self.assertEqual(records, ())
        self.assertEqual(dashboard.start_calls, 0)


class TestHangRestart(unittest.TestCase):
    def test_restarts_a_running_but_unresponsive_service(self):
        manager = WindowsServiceManager()
        stuck = _FakeService(running=True, responsive=False)
        manager.register_service("stuck", stuck.start, stuck.stop, stuck.is_running, stuck.is_responsive)

        records = manager.check_and_restart_hung(T0)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].reason, RestartReason.HANG_DETECTED)
        self.assertEqual(stuck.stop_calls, 1)
        self.assertEqual(stuck.start_calls, 1)


class TestMT5NeverRestartedDuringActiveTrade(unittest.TestCase):
    def test_hung_mt5_is_not_restarted_while_a_trade_is_executing(self):
        manager = WindowsServiceManager(trade_in_progress=lambda: True)
        mt5 = _FakeService(running=True, responsive=False)
        manager.register_service(MT5_SERVICE_NAME, mt5.start, mt5.stop, mt5.is_running, mt5.is_responsive)

        records = manager.check_and_restart_hung(T0)

        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].succeeded)
        self.assertIn("deferred", records[0].detail)
        self.assertEqual(mt5.stop_calls, 0)
        self.assertEqual(mt5.start_calls, 0)

    def test_crashed_mt5_is_not_restarted_while_a_trade_is_executing(self):
        manager = WindowsServiceManager(trade_in_progress=lambda: True)
        mt5 = _FakeService(running=False)
        manager.register_service(MT5_SERVICE_NAME, mt5.start, mt5.stop, mt5.is_running, mt5.is_responsive)

        records = manager.check_and_restart_crashed(T0)

        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].succeeded)
        self.assertEqual(mt5.start_calls, 0)

    def test_mt5_is_restarted_normally_once_no_trade_is_in_progress(self):
        manager = WindowsServiceManager(trade_in_progress=lambda: False)
        mt5 = _FakeService(running=False)
        manager.register_service(MT5_SERVICE_NAME, mt5.start, mt5.stop, mt5.is_running, mt5.is_responsive)

        records = manager.check_and_restart_crashed(T0)

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].succeeded)
        self.assertEqual(mt5.start_calls, 1)

    def test_other_services_are_unaffected_by_the_mt5_trade_guard(self):
        manager = WindowsServiceManager(trade_in_progress=lambda: True)
        dashboard = _FakeService(running=False)
        manager.register_service("dashboard", dashboard.start, dashboard.stop, dashboard.is_running, dashboard.is_responsive)

        records = manager.check_and_restart_crashed(T0)

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].succeeded)


class TestHealthCheckAll(unittest.TestCase):
    def test_reports_crashed_degraded_and_healthy_correctly(self):
        manager = WindowsServiceManager()
        healthy = _FakeService(running=True, responsive=True)
        degraded = _FakeService(running=True, responsive=False)
        crashed = _FakeService(running=False)
        manager.register_service("healthy", healthy.start, healthy.stop, healthy.is_running, healthy.is_responsive)
        manager.register_service("degraded", degraded.start, degraded.stop, degraded.is_running, degraded.is_responsive)
        manager.register_service("crashed", crashed.start, crashed.stop, crashed.is_running, crashed.is_responsive)

        statuses = {s.name: s.state for s in manager.health_check_all(T0)}

        self.assertEqual(statuses["healthy"], ServiceState.RUNNING)
        self.assertEqual(statuses["degraded"], ServiceState.DEGRADED)
        self.assertEqual(statuses["crashed"], ServiceState.CRASHED)


if __name__ == "__main__":
    unittest.main()
