"""Pure health-derivation/aggregation/eligibility function tests (ADR-011
§5, §6, §7, §9)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.watchdog import checks
from phantom_pipeline.watchdog.models import (
    ComponentHealth,
    ComponentKind,
    HealthState,
)
from tests.phantom_pipeline.watchdog._fixtures import T0, make_config, make_signal


class TestDeriveHeartbeatStatus(unittest.TestCase):
    def test_never_observed_is_not_expired_and_has_no_last_seen(self):
        config = make_config()
        status = checks.derive_heartbeat_status("scanner", None, T0, config)
        self.assertIsNone(status.last_seen_at)
        self.assertFalse(status.expired)
        self.assertEqual(status.missed_count, 0)

    def test_fresh_heartbeat_has_zero_missed_count(self):
        config = make_config(default_heartbeat_interval_seconds=30.0)
        status = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=5), config)
        self.assertEqual(status.missed_count, 0)
        self.assertFalse(status.expired)

    def test_missed_count_scales_with_age(self):
        config = make_config(default_heartbeat_interval_seconds=30.0)
        status = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=95), config)
        self.assertEqual(status.missed_count, 3)

    def test_heartbeat_expired_beyond_max_age_multiplier(self):
        config = make_config(default_heartbeat_interval_seconds=30.0, heartbeat_max_age_multiplier=10.0)
        status = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=301), config)
        self.assertTrue(status.expired)

    def test_heartbeat_not_expired_at_boundary(self):
        config = make_config(default_heartbeat_interval_seconds=30.0, heartbeat_max_age_multiplier=10.0)
        status = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=300), config)
        self.assertFalse(status.expired)


class TestDeriveComponentHealth(unittest.TestCase):
    def test_never_observed_is_unknown(self):
        config = make_config()
        heartbeat = checks.derive_heartbeat_status("scanner", None, T0, config)
        health = checks.derive_component_health(make_signal(), heartbeat, False, config, T0)
        self.assertEqual(health.state, HealthState.UNKNOWN)

    def test_healthy_heartbeat_with_no_reported_state_is_healthy(self):
        config = make_config()
        heartbeat = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=1), config)
        health = checks.derive_component_health(make_signal(), heartbeat, False, config, T0)
        self.assertEqual(health.state, HealthState.HEALTHY)

    def test_worse_of_heartbeat_and_reported_state_wins(self):
        config = make_config()
        heartbeat = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=1), config)
        signal = make_signal(reported_state=HealthState.CRITICAL, detail="reported by stage")
        health = checks.derive_component_health(signal, heartbeat, False, config, T0)
        self.assertEqual(health.state, HealthState.CRITICAL)

    def test_recovering_flag_produces_recovering_state_when_worse(self):
        config = make_config()
        heartbeat = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=1), config)
        health = checks.derive_component_health(make_signal(), heartbeat, True, config, T0)
        self.assertEqual(health.state, HealthState.RECOVERING)

    def test_lifecycle_reported_state_passes_through_directly(self):
        config = make_config()
        heartbeat = checks.derive_heartbeat_status("scanner", None, T0, config)
        signal = make_signal(reported_state=HealthState.STARTING, detail="booting")
        health = checks.derive_component_health(signal, heartbeat, False, config, T0)
        self.assertEqual(health.state, HealthState.STARTING)

    def test_shutdown_reported_state_passes_through_even_if_heartbeat_expired(self):
        config = make_config()
        heartbeat = checks.derive_heartbeat_status("scanner", T0, T0 + timedelta(seconds=10_000), config)
        signal = make_signal(reported_state=HealthState.SHUTDOWN, detail="planned maintenance")
        health = checks.derive_component_health(signal, heartbeat, False, config, T0 + timedelta(seconds=10_000))
        self.assertEqual(health.state, HealthState.SHUTDOWN)


class TestAggregateOverallHealth(unittest.TestCase):
    def _ch(self, state):
        return ComponentHealth("x", ComponentKind.PIPELINE_STAGE, state, "r", T0)

    def test_worst_of_wins_never_average(self):
        healths = [self._ch(HealthState.HEALTHY), self._ch(HealthState.CRITICAL), self._ch(HealthState.WARNING)]
        self.assertEqual(checks.aggregate_overall_health(healths), HealthState.CRITICAL)

    def test_unknown_is_at_least_as_severe_as_critical(self):
        healths = [self._ch(HealthState.UNKNOWN), self._ch(HealthState.WARNING)]
        self.assertEqual(checks.aggregate_overall_health(healths), HealthState.UNKNOWN)

    def test_empty_input_fails_closed_to_unknown(self):
        self.assertEqual(checks.aggregate_overall_health([]), HealthState.UNKNOWN)

    def test_starting_component_does_not_drag_to_critical(self):
        healths = [self._ch(HealthState.STARTING), self._ch(HealthState.HEALTHY)]
        self.assertEqual(checks.aggregate_overall_health(healths), HealthState.HEALTHY)

    def test_all_starting_reports_starting_not_healthy(self):
        healths = [self._ch(HealthState.STARTING)]
        self.assertEqual(checks.aggregate_overall_health(healths), HealthState.STARTING)


class TestRecoveryEligibility(unittest.TestCase):
    def test_frozen_component_is_not_eligible(self):
        config = make_config()
        eligible, reason = checks.is_recovery_eligible(HealthState.CRITICAL, True, False, 0, None, T0, config)
        self.assertFalse(eligible)
        self.assertIn("frozen", reason)

    def test_already_recovering_is_not_eligible(self):
        config = make_config()
        eligible, _ = checks.is_recovery_eligible(HealthState.CRITICAL, False, True, 0, None, T0, config)
        self.assertFalse(eligible)

    def test_healthy_component_is_not_eligible(self):
        config = make_config()
        eligible, _ = checks.is_recovery_eligible(HealthState.HEALTHY, False, False, 0, None, T0, config)
        self.assertFalse(eligible)

    def test_exceeding_bound_is_not_eligible(self):
        config = make_config(recovery_max_attempts=3)
        eligible, reason = checks.is_recovery_eligible(HealthState.CRITICAL, False, False, 3, None, T0, config)
        self.assertFalse(eligible)
        self.assertIn("bounded recovery", reason)

    def test_critical_component_within_bound_is_eligible(self):
        config = make_config(recovery_max_attempts=3, recovery_backoff_seconds=0.0)
        eligible, _ = checks.is_recovery_eligible(HealthState.CRITICAL, False, False, 1, None, T0, config)
        self.assertTrue(eligible)

    def test_backoff_blocks_immediate_retry(self):
        config = make_config(recovery_backoff_seconds=60.0)
        eligible, reason = checks.is_recovery_eligible(
            HealthState.CRITICAL, False, False, 1, T0, T0 + timedelta(seconds=5), config
        )
        self.assertFalse(eligible)
        self.assertIn("backoff", reason)


if __name__ == "__main__":
    unittest.main()
