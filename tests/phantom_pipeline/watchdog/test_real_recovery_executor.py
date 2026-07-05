"""RealRecoveryActionExecutor tests. `command_runner`/`signal_sender` are
injected fakes, mirroring every other real adapter's own "no live external
dependency in unit tests" discipline — `ROTATE_LOGS` is the one action
exercised against a genuine (temporary) file, since it needs no external
process at all."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import List, Sequence, Tuple

from phantom_pipeline.watchdog.models import RecoveryActionType
from phantom_pipeline.watchdog.real_recovery_executor import RealRecoveryActionExecutor


class _FakeCommandRunner:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: List[Tuple[Sequence[str], float]] = []

    def __call__(self, command: Sequence[str], timeout_seconds: float) -> bool:
        self.calls.append((tuple(command), timeout_seconds))
        return self.result


class _FakeSignalSender:
    def __init__(self) -> None:
        self.calls: List[Tuple[int, int]] = []

    def __call__(self, pid: int, sig: int) -> None:
        self.calls.append((pid, sig))


class TestServiceRestartActions(unittest.TestCase):
    def test_restart_service_calls_systemctl_for_configured_unit(self):
        runner = _FakeCommandRunner(result=True)
        executor = RealRecoveryActionExecutor(service_units={"scanner": "phantom-scanner.service"}, command_runner=runner)
        self.assertTrue(executor.execute("scanner", RecoveryActionType.RESTART_SERVICE))
        self.assertEqual(runner.calls[0][0], ("systemctl", "restart", "phantom-scanner.service"))

    def test_restart_worker_and_restart_monitoring_use_same_mechanism(self):
        runner = _FakeCommandRunner(result=True)
        executor = RealRecoveryActionExecutor(service_units={"scanner": "phantom-scanner.service"}, command_runner=runner)
        self.assertTrue(executor.execute("scanner", RecoveryActionType.RESTART_WORKER))
        self.assertTrue(executor.execute("scanner", RecoveryActionType.RESTART_MONITORING))
        self.assertEqual(len(runner.calls), 2)

    def test_restart_service_unconfigured_component_returns_false(self):
        executor = RealRecoveryActionExecutor(command_runner=_FakeCommandRunner())
        self.assertFalse(executor.execute("unknown_component", RecoveryActionType.RESTART_SERVICE))

    def test_restart_service_command_failure_returns_false(self):
        runner = _FakeCommandRunner(result=False)
        executor = RealRecoveryActionExecutor(service_units={"scanner": "phantom-scanner.service"}, command_runner=runner)
        self.assertFalse(executor.execute("scanner", RecoveryActionType.RESTART_SERVICE))


class TestCallbackActions(unittest.TestCase):
    def test_reconnect_dependency_invokes_configured_callback(self):
        calls = []
        executor = RealRecoveryActionExecutor(reconnect_callbacks={"mt5_bridge": lambda: calls.append(1) or True})
        self.assertTrue(executor.execute("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY))
        self.assertEqual(calls, [1])

    def test_rebuild_connection_uses_same_callback_map(self):
        executor = RealRecoveryActionExecutor(reconnect_callbacks={"data_pipeline": lambda: True})
        self.assertTrue(executor.execute("data_pipeline", RecoveryActionType.REBUILD_CONNECTION))

    def test_clear_stale_heartbeat_uses_same_callback_map(self):
        executor = RealRecoveryActionExecutor(reconnect_callbacks={"watchdog": lambda: True})
        self.assertTrue(executor.execute("watchdog", RecoveryActionType.CLEAR_STALE_HEARTBEAT))

    def test_callback_returning_false_is_reported_as_failure(self):
        executor = RealRecoveryActionExecutor(reconnect_callbacks={"mt5_bridge": lambda: False})
        self.assertFalse(executor.execute("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY))

    def test_unconfigured_callback_component_returns_false(self):
        executor = RealRecoveryActionExecutor()
        self.assertFalse(executor.execute("unknown", RecoveryActionType.RECONNECT_DEPENDENCY))

    def test_callback_raising_is_caught_and_reported_as_failure(self):
        def _raises():
            raise RuntimeError("boom")

        executor = RealRecoveryActionExecutor(reconnect_callbacks={"mt5_bridge": _raises})
        self.assertFalse(executor.execute("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY))


class TestReloadConfiguration(unittest.TestCase):
    def test_reload_configuration_sends_sighup_to_pid_in_pidfile(self):
        sender = _FakeSignalSender()
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as handle:
            handle.write("4242")
            pidfile_path = handle.name
        try:
            executor = RealRecoveryActionExecutor(
                reload_pidfiles={"risk_engine": pidfile_path}, signal_sender=sender
            )
            self.assertTrue(executor.execute("risk_engine", RecoveryActionType.RELOAD_CONFIGURATION))
            self.assertEqual(sender.calls, [(4242, 1)])  # signal.SIGHUP == 1
        finally:
            os.unlink(pidfile_path)

    def test_reload_configuration_unconfigured_component_returns_false(self):
        executor = RealRecoveryActionExecutor()
        self.assertFalse(executor.execute("unknown", RecoveryActionType.RELOAD_CONFIGURATION))

    def test_reload_configuration_missing_pidfile_returns_false(self):
        executor = RealRecoveryActionExecutor(reload_pidfiles={"risk_engine": "/nonexistent/path/pidfile"})
        self.assertFalse(executor.execute("risk_engine", RecoveryActionType.RELOAD_CONFIGURATION))

    def test_reload_configuration_malformed_pidfile_returns_false(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as handle:
            handle.write("not-a-pid")
            pidfile_path = handle.name
        try:
            executor = RealRecoveryActionExecutor(reload_pidfiles={"risk_engine": pidfile_path})
            self.assertFalse(executor.execute("risk_engine", RecoveryActionType.RELOAD_CONFIGURATION))
        finally:
            os.unlink(pidfile_path)


class TestRotateLogs(unittest.TestCase):
    def test_rotate_logs_moves_file_and_creates_fresh_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "component.log")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("old log contents")

            executor = RealRecoveryActionExecutor(log_paths={"analytics": log_path})
            self.assertTrue(executor.execute("analytics", RecoveryActionType.ROTATE_LOGS))

            self.assertTrue(os.path.exists(log_path))
            with open(log_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "")

            rotated_files = [f for f in os.listdir(tmpdir) if f != "component.log"]
            self.assertEqual(len(rotated_files), 1)
            with open(os.path.join(tmpdir, rotated_files[0]), "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "old log contents")

    def test_rotate_logs_unconfigured_component_returns_false(self):
        executor = RealRecoveryActionExecutor()
        self.assertFalse(executor.execute("unknown", RecoveryActionType.ROTATE_LOGS))

    def test_rotate_logs_missing_file_returns_false(self):
        executor = RealRecoveryActionExecutor(log_paths={"analytics": "/nonexistent/log/path.log"})
        self.assertFalse(executor.execute("analytics", RecoveryActionType.ROTATE_LOGS))


class TestNeverRaises(unittest.TestCase):
    def test_execute_never_raises_even_on_internal_error(self):
        def _bad_runner(command, timeout_seconds):
            raise OSError("systemctl not found")

        executor = RealRecoveryActionExecutor(service_units={"scanner": "phantom-scanner.service"}, command_runner=_bad_runner)
        try:
            result = executor.execute("scanner", RecoveryActionType.RESTART_SERVICE)
        except Exception as exc:  # pragma: no cover - test fails via assertion below
            self.fail(f"execute() raised unexpectedly: {exc}")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
