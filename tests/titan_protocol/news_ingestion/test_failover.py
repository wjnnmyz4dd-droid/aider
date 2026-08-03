"""Tests for `NewsFailoverEngine` -- primary/backup selection, the six
named failure classes, deterministic (not opportunistic) recovery, and
the fail-closed both-providers-down path (ADR-033 SS4.2, Phase 3E
mission's own TESTING list)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.news_ingestion.failover import NewsFailoverEngine
from titan_protocol.news_ingestion.metrics import NewsIngestionMetrics
from titan_protocol.news_ingestion.models import (
    ProviderAuthenticationFailed,
    ProviderName,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderTimeout,
    ProviderUnavailable,
    TrustState,
)

from ._fixtures import FakeProvider, T0, make_config, make_normalized_event


class TestPrimarySuccess(unittest.TestCase):
    def test_trading_economics_success_is_served_directly(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [(make_normalized_event("p1"),)])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [])
        engine = NewsFailoverEngine(make_config(), primary, backup)
        events, trusted = engine.fetch_events(T0)
        self.assertTrue(trusted)
        self.assertEqual([e.event_id for e in events], ["p1"])
        self.assertEqual(backup.call_count, 0)  # backup never consulted while primary is healthy


class TestBackupSuccess(unittest.TestCase):
    def test_forex_factory_success_is_served_after_primary_failure(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [ProviderUnavailable("down")])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [(make_normalized_event("b1"),)])
        engine = NewsFailoverEngine(make_config(), primary, backup)
        events, trusted = engine.fetch_events(T0)
        self.assertTrue(trusted)
        self.assertEqual([e.event_id for e in events], ["b1"])


class TestPrimaryFailureClasses(unittest.TestCase):
    def _assert_failover_on(self, exc):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [exc])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [(make_normalized_event("b1"),)])
        engine = NewsFailoverEngine(make_config(), primary, backup)
        events, trusted = engine.fetch_events(T0)
        self.assertTrue(trusted)
        self.assertEqual([e.event_id for e in events], ["b1"])
        snapshot = engine.health_snapshot(T0)
        self.assertEqual(snapshot.active_provider, ProviderName.FOREX_FACTORY)
        self.assertEqual(snapshot.failover_state.failover_count, 1)

    def test_primary_timeout_triggers_failover(self):
        self._assert_failover_on(ProviderTimeout("timed out"))

    def test_primary_malformed_payload_triggers_failover(self):
        self._assert_failover_on(ProviderSchemaError("bad shape"))

    def test_primary_authentication_failure_triggers_failover(self):
        self._assert_failover_on(ProviderAuthenticationFailed("bad key"))

    def test_primary_rate_limited_triggers_failover(self):
        self._assert_failover_on(ProviderRateLimited("429"))

    def test_primary_unavailable_triggers_failover(self):
        self._assert_failover_on(ProviderUnavailable("connection refused"))


class TestAutomaticFailoverAndRecovery(unittest.TestCase):
    def test_recovery_requires_n_consecutive_successes_not_a_single_lucky_one(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [
            ProviderTimeout("t1"),
            (make_normalized_event("p1"),),  # 1st success -- not enough (threshold=3)
            (make_normalized_event("p2"),),  # 2nd success -- still not enough
            (make_normalized_event("p3"),),  # 3rd consecutive success -- recovers here
        ])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [
            (make_normalized_event("b1"),),
            (make_normalized_event("b2"),),
            (make_normalized_event("b3"),),
        ])
        engine = NewsFailoverEngine(make_config(recovery_health_check_count=3), primary, backup)

        events0, _ = engine.fetch_events(T0)
        self.assertEqual([e.event_id for e in events0], ["b1"])  # failed over

        events1, _ = engine.fetch_events(T0 + timedelta(minutes=1))
        self.assertEqual([e.event_id for e in events1], ["b2"])  # primary's 1st success -- still serving backup

        events2, _ = engine.fetch_events(T0 + timedelta(minutes=2))
        # primary's 2nd consecutive success -- still not enough; backup still serves.
        self.assertEqual([e.event_id for e in events2], ["b3"])
        self.assertEqual(backup.call_count, 3)

        events3, _ = engine.fetch_events(T0 + timedelta(minutes=3))
        self.assertEqual([e.event_id for e in events3], ["p3"])  # recovered -- primary now serving

        snapshot = engine.health_snapshot(T0 + timedelta(minutes=4))
        self.assertEqual(snapshot.active_provider, ProviderName.TRADING_ECONOMICS)
        self.assertEqual(snapshot.failover_state.failover_count, 1)
        self.assertEqual(snapshot.failover_state.recovery_count, 1)

    def test_recovery_resets_if_a_success_streak_is_broken(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [
            ProviderTimeout("t1"),
            (make_normalized_event("p1"),),
            ProviderTimeout("t2"),  # breaks the streak
            (make_normalized_event("p2"),),
            (make_normalized_event("p3"),),
        ])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [
            (make_normalized_event("b1"),),
            (make_normalized_event("b2"),),
            (make_normalized_event("b3"),),
            (make_normalized_event("b4"),),
        ])
        engine = NewsFailoverEngine(make_config(recovery_health_check_count=2), primary, backup)
        for i in range(5):
            engine.fetch_events(T0 + timedelta(minutes=i))
        snapshot = engine.health_snapshot(T0 + timedelta(minutes=5))
        # Only 2 consecutive successes (p2, p3) ever occurred in a row -- recovers exactly once.
        self.assertEqual(snapshot.active_provider, ProviderName.TRADING_ECONOMICS)
        self.assertEqual(snapshot.failover_state.recovery_count, 1)


class TestBothProvidersUnavailable(unittest.TestCase):
    def test_both_down_fails_closed(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [ProviderUnavailable("down")])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [ProviderTimeout("down too")])
        metrics = NewsIngestionMetrics()
        engine = NewsFailoverEngine(make_config(), primary, backup, metrics)
        events, trusted = engine.fetch_events(T0)
        self.assertFalse(trusted)
        self.assertEqual(events, ())
        self.assertEqual(metrics.dual_outage_count, 1)

    def test_health_snapshot_reports_untrusted_when_both_stale(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [ProviderUnavailable("down")])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [ProviderTimeout("down too")])
        engine = NewsFailoverEngine(make_config(stale_after_seconds=1.0), primary, backup)
        engine.fetch_events(T0)
        snapshot = engine.health_snapshot(T0 + timedelta(seconds=10))
        self.assertFalse(snapshot.trusted)
        for health in snapshot.provider_health:
            self.assertEqual(health.trust_state, TrustState.UNTRUSTED)


class TestNoMergeAverageOrVote(unittest.TestCase):
    def test_events_always_come_from_exactly_one_provider_never_combined(self):
        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [(make_normalized_event("p1", provider=ProviderName.TRADING_ECONOMICS),)])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [(make_normalized_event("b1", provider=ProviderName.FOREX_FACTORY),)])
        engine = NewsFailoverEngine(make_config(), primary, backup)
        events, _ = engine.fetch_events(T0)
        providers_seen = {e.provider for e in events}
        self.assertEqual(len(providers_seen), 1)


if __name__ == "__main__":
    unittest.main()
