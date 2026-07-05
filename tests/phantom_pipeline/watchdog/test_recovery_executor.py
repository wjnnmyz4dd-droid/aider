"""`RecoveryActionExecutor` tests — the fake double never touches any
real process/service, and its outcomes are fully deterministic/scriptable
(mirroring `mt5_bridge.broker_adapter`'s own test-double discipline)."""

from __future__ import annotations

import unittest

from phantom_pipeline.watchdog.models import RecoveryActionType
from phantom_pipeline.watchdog.recovery_executor import FakeRecoveryActionExecutor


class TestFakeRecoveryActionExecutor(unittest.TestCase):
    def test_default_result_used_when_not_scripted(self):
        executor = FakeRecoveryActionExecutor(default_result=True)
        self.assertTrue(executor.execute("scanner", RecoveryActionType.RESTART_SERVICE))

    def test_scripted_result_overrides_default(self):
        executor = FakeRecoveryActionExecutor(default_result=True)
        executor.set_result("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY, False)
        self.assertFalse(executor.execute("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY))
        self.assertTrue(executor.execute("scanner", RecoveryActionType.RESTART_SERVICE))

    def test_attempts_are_recorded(self):
        executor = FakeRecoveryActionExecutor()
        executor.execute("scanner", RecoveryActionType.RESTART_SERVICE)
        executor.execute("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY)
        self.assertEqual(
            executor.attempts,
            [("scanner", RecoveryActionType.RESTART_SERVICE), ("mt5_bridge", RecoveryActionType.RECONNECT_DEPENDENCY)],
        )


if __name__ == "__main__":
    unittest.main()
