"""Pure alert-classification tests (ADR-011 §11)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.watchdog import alerting
from phantom_pipeline.watchdog.models import AlertClass, ComponentHealth, ComponentKind, HealthState
from tests.phantom_pipeline.watchdog._fixtures import T0, make_config


def _ch(state, reason="r"):
    return ComponentHealth("scanner", ComponentKind.PIPELINE_STAGE, state, reason, T0)


class TestClassifyAlert(unittest.TestCase):
    def test_critical_state_is_critical_alert(self):
        self.assertEqual(alerting.classify_alert(_ch(HealthState.CRITICAL)), AlertClass.CRITICAL)

    def test_offline_state_is_critical_alert(self):
        self.assertEqual(alerting.classify_alert(_ch(HealthState.OFFLINE)), AlertClass.CRITICAL)

    def test_warning_and_degraded_are_warning_alert(self):
        self.assertEqual(alerting.classify_alert(_ch(HealthState.WARNING)), AlertClass.WARNING)
        self.assertEqual(alerting.classify_alert(_ch(HealthState.DEGRADED)), AlertClass.WARNING)

    def test_recovering_is_recovery_alert(self):
        self.assertEqual(alerting.classify_alert(_ch(HealthState.RECOVERING)), AlertClass.RECOVERY)

    def test_healthy_produces_no_alert(self):
        self.assertIsNone(alerting.classify_alert(_ch(HealthState.HEALTHY)))

    def test_shutdown_is_suppressed(self):
        """The only condition under which an alert is suppressed (ADR-011
        §11) — always deliberate and operator-visible."""
        self.assertIsNone(alerting.classify_alert(_ch(HealthState.SHUTDOWN)))

    def test_unknown_produces_a_critical_alert(self):
        """`UNKNOWN` is at least as severe as `CRITICAL` (§6) — silently
        producing no alert for it would violate "never hide failures"
        (Hard Rules)."""
        self.assertEqual(alerting.classify_alert(_ch(HealthState.UNKNOWN)), AlertClass.CRITICAL)


class TestShouldEscalate(unittest.TestCase):
    def test_escalates_beyond_configured_duration(self):
        config = make_config(alert_escalation_duration_seconds=600.0)
        state_since = (HealthState.CRITICAL, T0)
        self.assertTrue(alerting.should_escalate("mt5_bridge", HealthState.CRITICAL, state_since, T0 + timedelta(seconds=601), config))

    def test_does_not_escalate_before_duration(self):
        config = make_config(alert_escalation_duration_seconds=600.0)
        state_since = (HealthState.CRITICAL, T0)
        self.assertFalse(alerting.should_escalate("mt5_bridge", HealthState.CRITICAL, state_since, T0 + timedelta(seconds=60), config))

    def test_no_escalation_for_non_critical_state(self):
        config = make_config()
        state_since = (HealthState.WARNING, T0)
        self.assertFalse(alerting.should_escalate("mt5_bridge", HealthState.WARNING, state_since, T0 + timedelta(seconds=10_000), config))


class TestResolveRepeatCount(unittest.TestCase):
    def test_first_alert_has_repeat_count_one(self):
        config = make_config()
        self.assertEqual(alerting.resolve_repeat_count("offline", None, T0, config), 1)

    def test_identical_alert_within_window_increments(self):
        config = make_config(alert_dedup_window_seconds=300.0)
        last_signature = ("offline", T0, 1)
        count = alerting.resolve_repeat_count("offline", last_signature, T0 + timedelta(seconds=10), config)
        self.assertEqual(count, 2)

    def test_different_detail_resets_to_one(self):
        config = make_config()
        last_signature = ("offline", T0, 5)
        count = alerting.resolve_repeat_count("different reason", last_signature, T0 + timedelta(seconds=10), config)
        self.assertEqual(count, 1)

    def test_outside_dedup_window_resets_to_one(self):
        config = make_config(alert_dedup_window_seconds=60.0)
        last_signature = ("offline", T0, 5)
        count = alerting.resolve_repeat_count("offline", last_signature, T0 + timedelta(seconds=100), config)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
