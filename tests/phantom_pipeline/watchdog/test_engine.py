"""WatchdogEngine integration tests — covers ADR-011 §14's Testing list:
crash recovery, heartbeat recovery, dependency failure, network
partition, database outage, MT5 disconnect (observing side), repeated
restart protection, alert generation, false-positive suppression, and
determinism."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.watchdog.config import WatchdogConfig
from phantom_pipeline.watchdog.engine import WatchdogEngine
from phantom_pipeline.watchdog.metrics import WatchdogMetrics
from phantom_pipeline.watchdog.models import (
    AlertClass,
    ComponentKind,
    HealthState,
    RecoveryActionType,
    RecoveryOutcome,
)
from phantom_pipeline.watchdog.recovery_executor import FakeRecoveryActionExecutor
from phantom_pipeline.watchdog.state_store import InMemoryWatchdogStateStore
from tests.phantom_pipeline.watchdog._fixtures import T0, make_config, make_signal


def _engine(config=None, executor=None, metrics=None):
    store = InMemoryWatchdogStateStore()
    executor = executor or FakeRecoveryActionExecutor()
    return WatchdogEngine(store, executor, config=config or make_config(), metrics=metrics), store, executor


class TestCrashRecovery(unittest.TestCase):
    def test_simulated_crash_triggers_restart_and_reports_recovering_then_healthy(self):
        engine, store, executor = _engine()
        engine.record_heartbeat("mt5_bridge", T0)

        # Heartbeat expires -> component goes OFFLINE (a "crash").
        crash_time = T0 + timedelta(seconds=10_000)
        health = engine.evaluate([make_signal("mt5_bridge")], crash_time)
        self.assertEqual(health.component_health[0].state, HealthState.OFFLINE)

        status, alert = engine.attempt_recovery(
            "mt5_bridge", RecoveryActionType.RESTART_SERVICE, health.component_health[0].state, crash_time
        )
        self.assertEqual(status.last_outcome, RecoveryOutcome.SUCCEEDED)
        self.assertEqual(alert.alert_class, AlertClass.RECOVERY)

        # A fresh heartbeat after restart clears the component back to HEALTHY.
        resumed_time = crash_time + timedelta(seconds=1)
        engine.record_heartbeat("mt5_bridge", resumed_time)
        health2 = engine.evaluate([make_signal("mt5_bridge")], resumed_time)
        self.assertEqual(health2.component_health[0].state, HealthState.HEALTHY)


class TestHeartbeatRecovery(unittest.TestCase):
    def test_missed_then_resumed_heartbeat_produces_correct_severity_transitions(self):
        config = make_config(default_heartbeat_interval_seconds=10.0, warning_missed_threshold=2, critical_missed_threshold=5)
        engine, store, _ = _engine(config)
        engine.record_heartbeat("scanner", T0)

        healthy = engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=5))
        self.assertEqual(healthy.component_health[0].state, HealthState.HEALTHY)

        warning = engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=25))
        self.assertEqual(warning.component_health[0].state, HealthState.WARNING)

        critical = engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=55))
        self.assertEqual(critical.component_health[0].state, HealthState.CRITICAL)

        # Resumed heartbeat brings it back to HEALTHY.
        resumed_time = T0 + timedelta(seconds=60)
        engine.record_heartbeat("scanner", resumed_time)
        recovered = engine.evaluate([make_signal("scanner")], resumed_time + timedelta(seconds=1))
        self.assertEqual(recovered.component_health[0].state, HealthState.HEALTHY)


class TestDependencyFailure(unittest.TestCase):
    def test_simulated_dependency_failure_reflected_in_component_health(self):
        engine, store, _ = _engine()
        for component in ("mt5_broker_feed", "news", "database", "secrets"):
            engine.record_heartbeat(component, T0)

        signals = [
            make_signal("mt5_broker_feed", kind=ComponentKind.EXTERNAL_DEPENDENCY, reported_state=HealthState.CRITICAL, detail="feed unreachable"),
            make_signal("news", kind=ComponentKind.EXTERNAL_DEPENDENCY, reported_state=HealthState.HEALTHY),
            make_signal("database", kind=ComponentKind.EXTERNAL_DEPENDENCY, reported_state=HealthState.OFFLINE, detail="outage"),
            make_signal("secrets", kind=ComponentKind.EXTERNAL_DEPENDENCY, reported_state=HealthState.HEALTHY),
        ]
        health = engine.evaluate(signals, T0 + timedelta(seconds=1))
        by_component = {c.component: c for c in health.component_health}
        self.assertEqual(by_component["mt5_broker_feed"].state, HealthState.CRITICAL)
        self.assertEqual(by_component["database"].state, HealthState.OFFLINE)
        self.assertEqual(by_component["news"].state, HealthState.HEALTHY)
        self.assertEqual(health.overall_health, HealthState.OFFLINE)


class TestNetworkPartition(unittest.TestCase):
    def test_simulated_network_loss_produces_critical_or_offline_not_a_silent_gap(self):
        engine, store, _ = _engine()
        engine.record_heartbeat("network", T0)
        signal = make_signal("network", kind=ComponentKind.EXTERNAL_DEPENDENCY, reported_state=HealthState.OFFLINE, detail="network partition")
        health = engine.evaluate([signal], T0 + timedelta(seconds=1))
        self.assertEqual(health.component_health[0].state, HealthState.OFFLINE)
        self.assertNotEqual(health.overall_health, HealthState.HEALTHY)


class TestDatabaseOutage(unittest.TestCase):
    def test_database_outage_reported_and_does_not_crash_the_watchdog(self):
        engine, store, _ = _engine()
        signal = make_signal("database", kind=ComponentKind.EXTERNAL_DEPENDENCY, reported_state=HealthState.OFFLINE, detail="db outage")
        try:
            health = engine.evaluate([signal], T0)
        except Exception as exc:  # pragma: no cover - the test itself asserts this never happens
            self.fail(f"evaluate() raised on a dependency outage: {exc}")
        self.assertEqual(health.component_health[0].state, HealthState.OFFLINE)


class TestMT5DisconnectObservingSide(unittest.TestCase):
    def test_watchdog_reflects_mt5_bridges_own_reported_connection_state(self):
        """Mirrors ADR-008 §13's disconnect/reconnect tests from the
        Watchdog's observing side — it reflects MT5 Bridge's own reported
        state, never re-deriving it independently."""
        engine, store, _ = _engine()
        engine.record_heartbeat("mt5_bridge", T0)
        disconnected = make_signal("mt5_bridge", reported_state=HealthState.CRITICAL, detail="ConnectionState.DISCONNECTED")
        health = engine.evaluate([disconnected], T0 + timedelta(seconds=1))
        self.assertEqual(health.component_health[0].state, HealthState.CRITICAL)
        self.assertEqual(health.component_health[0].reason, "ConnectionState.DISCONNECTED")

        engine.record_heartbeat("mt5_bridge", T0 + timedelta(seconds=2))
        reconnected = make_signal("mt5_bridge", reported_state=HealthState.HEALTHY)
        health2 = engine.evaluate([reconnected], T0 + timedelta(seconds=3))
        self.assertEqual(health2.component_health[0].state, HealthState.HEALTHY)


class TestRepeatedRestartProtection(unittest.TestCase):
    def test_exceeding_bounded_recovery_attempts_freezes_recovery(self):
        config = make_config(recovery_max_attempts=2, recovery_backoff_seconds=0.0)
        executor = FakeRecoveryActionExecutor(default_result=False)
        engine, store, _ = _engine(config, executor=executor)

        t = T0
        for _ in range(2):
            status, _ = engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, t)
            t += timedelta(seconds=1)

        self.assertTrue(store.is_frozen("scanner"))

        # A further attempt is refused — the Watchdog does not loop indefinitely.
        status, alert = engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, t)
        self.assertFalse(status.in_progress)
        self.assertTrue(status.frozen)
        self.assertIsNone(alert)
        self.assertEqual(len(executor.attempts), 2)

    def test_frozen_component_stays_reported_at_true_severity(self):
        config = make_config(recovery_max_attempts=1, recovery_backoff_seconds=0.0)
        executor = FakeRecoveryActionExecutor(default_result=False)
        engine, store, _ = _engine(config, executor=executor)
        engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, T0)
        self.assertTrue(store.is_frozen("scanner"))

        # Heartbeat still missing -> component remains OFFLINE/CRITICAL, never fabricated HEALTHY.
        health = engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=1))
        self.assertNotEqual(health.component_health[0].state, HealthState.HEALTHY)

    def test_fresh_directly_observed_healthy_signal_clears_freeze(self):
        config = make_config(recovery_max_attempts=1, recovery_backoff_seconds=0.0, default_heartbeat_interval_seconds=30.0)
        executor = FakeRecoveryActionExecutor(default_result=False)
        engine, store, _ = _engine(config, executor=executor)
        engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, T0)
        self.assertTrue(store.is_frozen("scanner"))

        engine.record_heartbeat("scanner", T0 + timedelta(seconds=1))
        engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=2))
        self.assertFalse(store.is_frozen("scanner"))


class TestAlertGeneration(unittest.TestCase):
    def test_every_severity_transition_produces_the_correct_alert_class(self):
        engine, store, _ = _engine()
        cases = [
            (HealthState.CRITICAL, AlertClass.CRITICAL),
            (HealthState.OFFLINE, AlertClass.CRITICAL),
            (HealthState.WARNING, AlertClass.WARNING),
            (HealthState.DEGRADED, AlertClass.WARNING),
            (HealthState.RECOVERING, AlertClass.RECOVERY),
        ]
        for i, (state, expected_class) in enumerate(cases):
            engine.record_heartbeat(f"comp{i}", T0)
            signal = make_signal(f"comp{i}", reported_state=state)
            health = engine.evaluate([signal], T0 + timedelta(seconds=1))
            alerts = engine.generate_alerts(health, T0 + timedelta(seconds=1))
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].alert_class, expected_class)

    def test_shutdown_alert_is_suppressed(self):
        engine, store, _ = _engine()
        signal = make_signal("scanner", reported_state=HealthState.SHUTDOWN, detail="planned maintenance")
        health = engine.evaluate([signal], T0)
        alerts = engine.generate_alerts(health, T0)
        self.assertEqual(alerts, ())

    def test_healthy_component_produces_no_alert(self):
        engine, store, _ = _engine()
        engine.record_heartbeat("scanner", T0)
        health = engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=1))
        alerts = engine.generate_alerts(health, T0 + timedelta(seconds=1))
        self.assertEqual(alerts, ())

    def test_repeated_identical_alert_within_window_collapses_with_repeat_count(self):
        config = make_config(alert_dedup_window_seconds=300.0)
        engine, store, _ = _engine(config)
        engine.record_heartbeat("scanner", T0)
        signal = make_signal("scanner", reported_state=HealthState.CRITICAL, detail="down")
        health1 = engine.evaluate([signal], T0 + timedelta(seconds=1))
        alerts1 = engine.generate_alerts(health1, T0 + timedelta(seconds=1))
        health2 = engine.evaluate([signal], T0 + timedelta(seconds=10))
        alerts2 = engine.generate_alerts(health2, T0 + timedelta(seconds=10))
        self.assertEqual(alerts1[0].repeat_count, 1)
        self.assertEqual(alerts2[0].repeat_count, 2)

    def test_escalation_beyond_configured_duration(self):
        config = make_config(alert_escalation_duration_seconds=100.0)
        engine, store, _ = _engine(config)
        engine.record_heartbeat("scanner", T0)
        signal = make_signal("scanner", reported_state=HealthState.CRITICAL, detail="down")
        engine.generate_alerts(engine.evaluate([signal], T0 + timedelta(seconds=1)), T0 + timedelta(seconds=1))
        health_later = engine.evaluate([signal], T0 + timedelta(seconds=200))
        alerts = engine.generate_alerts(health_later, T0 + timedelta(seconds=200))
        self.assertEqual(alerts[0].alert_class, AlertClass.ESCALATION)


class TestFalsePositiveSuppression(unittest.TestCase):
    def test_single_missed_heartbeat_below_threshold_does_not_trigger_critical(self):
        config = make_config(default_heartbeat_interval_seconds=10.0, warning_missed_threshold=2, critical_missed_threshold=5)
        engine, store, _ = _engine(config)
        engine.record_heartbeat("scanner", T0)
        # One missed interval (age just over one interval) is below the
        # warning threshold entirely.
        health = engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=15))
        self.assertEqual(health.component_health[0].state, HealthState.HEALTHY)
        alerts = engine.generate_alerts(health, T0 + timedelta(seconds=15))
        self.assertEqual(alerts, ())


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_and_store_state_produce_identical_system_health(self):
        config = make_config()
        store1 = InMemoryWatchdogStateStore()
        store2 = InMemoryWatchdogStateStore()
        engine1 = WatchdogEngine(store1, FakeRecoveryActionExecutor(), config=config)
        engine2 = WatchdogEngine(store2, FakeRecoveryActionExecutor(), config=config)

        engine1.record_heartbeat("scanner", T0)
        engine2.record_heartbeat("scanner", T0)

        signal = make_signal("scanner")
        health1 = engine1.evaluate([signal], T0 + timedelta(seconds=5))
        health2 = engine2.evaluate([signal], T0 + timedelta(seconds=5))

        self.assertEqual(health1.overall_health, health2.overall_health)
        self.assertEqual(health1.component_health, health2.component_health)
        self.assertEqual(health1.trace_id, health2.trace_id)

    def test_recovery_policy_deterministic_given_same_history_and_config(self):
        config = make_config(recovery_max_attempts=2, recovery_backoff_seconds=0.0)
        executor1 = FakeRecoveryActionExecutor(default_result=False)
        executor2 = FakeRecoveryActionExecutor(default_result=False)
        engine1, store1, _ = _engine(config, executor=executor1)
        engine2, store2, _ = _engine(config, executor=executor2)

        for engine in (engine1, engine2):
            engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, T0)
            engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, T0 + timedelta(seconds=1))

        self.assertEqual(store1.is_frozen("scanner"), store2.is_frozen("scanner"))
        self.assertTrue(store1.is_frozen("scanner"))


class TestMetricsIntegration(unittest.TestCase):
    def test_evaluate_and_attempt_recovery_record_metrics(self):
        metrics = WatchdogMetrics()
        engine, store, _ = _engine(metrics=metrics)
        engine.record_heartbeat("scanner", T0)
        engine.evaluate([make_signal("scanner")], T0 + timedelta(seconds=1))
        self.assertEqual(metrics.state_counts.get("HEALTHY"), 1)

        engine.attempt_recovery("scanner", RecoveryActionType.RESTART_SERVICE, HealthState.CRITICAL, T0 + timedelta(seconds=2))
        self.assertEqual(metrics.restart_count, 1)


if __name__ == "__main__":
    unittest.main()
