"""State store tests (ADR-011 §7, §8, §9, §11) — bounded/pruned history,
freeze lifecycle, alert-dedup signatures scoped per (component, class)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.watchdog.models import AlertClass, HealthState, RecoveryActionType, RecoveryOutcome
from phantom_pipeline.watchdog.state_store import InMemoryWatchdogStateStore
from tests.phantom_pipeline.watchdog._fixtures import T0


class TestHeartbeatHistory(unittest.TestCase):
    def test_last_heartbeat_at_returns_most_recent(self):
        store = InMemoryWatchdogStateStore()
        store.record_heartbeat("scanner", T0, ttl_seconds=3600.0, max_history=500)
        store.record_heartbeat("scanner", T0 + timedelta(seconds=30), ttl_seconds=3600.0, max_history=500)
        self.assertEqual(store.last_heartbeat_at("scanner"), T0 + timedelta(seconds=30))

    def test_history_pruned_beyond_ttl(self):
        store = InMemoryWatchdogStateStore()
        store.record_heartbeat("scanner", T0, ttl_seconds=10.0, max_history=500)
        store.record_heartbeat("scanner", T0 + timedelta(seconds=100), ttl_seconds=10.0, max_history=500)
        self.assertEqual(store.heartbeat_history("scanner"), (T0 + timedelta(seconds=100),))

    def test_history_bounded_by_max_len(self):
        store = InMemoryWatchdogStateStore()
        for i in range(10):
            store.record_heartbeat("scanner", T0 + timedelta(seconds=i), ttl_seconds=3600.0, max_history=3)
        self.assertEqual(len(store.heartbeat_history("scanner")), 3)

    def test_unknown_component_has_no_heartbeat(self):
        store = InMemoryWatchdogStateStore()
        self.assertIsNone(store.last_heartbeat_at("never_seen"))


class TestFreezeLifecycle(unittest.TestCase):
    def test_freeze_and_clear(self):
        store = InMemoryWatchdogStateStore()
        self.assertFalse(store.is_frozen("mt5_bridge"))
        store.freeze("mt5_bridge")
        self.assertTrue(store.is_frozen("mt5_bridge"))
        store.clear_freeze("mt5_bridge")
        self.assertFalse(store.is_frozen("mt5_bridge"))


class TestRecoveryAttempts(unittest.TestCase):
    def test_attempts_in_window_counts_only_recent(self):
        store = InMemoryWatchdogStateStore()
        store.record_recovery_attempt("scanner", T0, window_seconds=60.0)
        store.record_recovery_attempt("scanner", T0 + timedelta(seconds=30), window_seconds=60.0)
        store.record_recovery_attempt("scanner", T0 + timedelta(seconds=200), window_seconds=60.0)
        self.assertEqual(store.attempts_in_window("scanner", T0 + timedelta(seconds=200), 60.0), 1)

    def test_recovery_outcome_recorded(self):
        store = InMemoryWatchdogStateStore()
        store.record_recovery_outcome("scanner", RecoveryActionType.RESTART_SERVICE, RecoveryOutcome.SUCCEEDED)
        self.assertEqual(store.last_action("scanner"), RecoveryActionType.RESTART_SERVICE)
        self.assertEqual(store.last_outcome("scanner"), RecoveryOutcome.SUCCEEDED)

    def test_recovering_flag_toggles(self):
        store = InMemoryWatchdogStateStore()
        self.assertFalse(store.is_recovering("scanner"))
        store.set_recovering("scanner", True)
        self.assertTrue(store.is_recovering("scanner"))
        store.set_recovering("scanner", False)
        self.assertFalse(store.is_recovering("scanner"))


class TestStateSinceAndAlertDedup(unittest.TestCase):
    def test_state_since_only_updates_on_transition(self):
        store = InMemoryWatchdogStateStore()
        store.record_state("scanner", HealthState.CRITICAL, T0)
        store.record_state("scanner", HealthState.CRITICAL, T0 + timedelta(seconds=60))
        state, since = store.state_since("scanner")
        self.assertEqual(state, HealthState.CRITICAL)
        self.assertEqual(since, T0)

    def test_alert_signature_scoped_per_component_and_class(self):
        store = InMemoryWatchdogStateStore()
        store.record_alert("scanner", AlertClass.CRITICAL, "offline", T0, 1)
        store.record_alert("scanner", AlertClass.RECOVERY, "restart succeeded", T0, 1)
        critical_sig = store.last_alert_signature("scanner", AlertClass.CRITICAL)
        recovery_sig = store.last_alert_signature("scanner", AlertClass.RECOVERY)
        self.assertEqual(critical_sig[0], "offline")
        self.assertEqual(recovery_sig[0], "restart succeeded")


if __name__ == "__main__":
    unittest.main()
