"""Unit tests for InFlightCommandRegistry (pair-level in-flight command
guard -- fixes: RuntimeOrchestrator had no memory of a command it
already submitted for a pair, so it would submit a fresh one every
cycle with a new correlation_id for as long as compliance kept
approving)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.runtime.in_flight_commands import InFlightCommandRegistry

_NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


class TestHasUnresolved(unittest.TestCase):
    def test_untracked_pair_is_not_unresolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))

    def test_recently_submitted_pair_is_unresolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))
        self.assertEqual(registry.in_flight_count(), 1)

    def test_different_pair_is_unaffected(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        self.assertFalse(registry.has_unresolved("GBPUSD", _NOW))

    def test_expired_entry_is_not_unresolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=60.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=61)
        self.assertFalse(registry.has_unresolved("EURUSD", later))

    def test_entry_within_ttl_is_still_unresolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=60.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=59)
        self.assertTrue(registry.has_unresolved("EURUSD", later))


class TestReconcile(unittest.TestCase):
    def test_reconcile_drops_resolved_entries(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        dropped = registry.reconcile(_NOW, is_resolved=lambda cid: cid == "corr-1")
        self.assertEqual(dropped, 1)
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))

    def test_reconcile_keeps_unresolved_entries(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        dropped = registry.reconcile(_NOW, is_resolved=lambda cid: False)
        self.assertEqual(dropped, 0)
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))

    def test_reconcile_drops_expired_entries_even_if_unresolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=60.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=61)
        dropped = registry.reconcile(later, is_resolved=lambda cid: False)
        self.assertEqual(dropped, 1)

    def test_reconcile_only_drops_matching_entries(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.record_submission("GBPUSD", "corr-2", _NOW)
        dropped = registry.reconcile(_NOW, is_resolved=lambda cid: cid == "corr-1")
        self.assertEqual(dropped, 1)
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))
        self.assertTrue(registry.has_unresolved("GBPUSD", _NOW))
        self.assertEqual(registry.in_flight_count(), 1)


class TestResubmissionAfterResolution(unittest.TestCase):
    def test_pair_can_be_resubmitted_once_resolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))
        registry.record_submission("EURUSD", "corr-2", _NOW)
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))
        self.assertEqual(registry.correlation_id_for("EURUSD"), "corr-2")


class TestCorrelationIdFor(unittest.TestCase):
    def test_returns_none_for_untracked_pair(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        self.assertIsNone(registry.correlation_id_for("EURUSD"))

    def test_returns_tracked_correlation_id(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        self.assertEqual(registry.correlation_id_for("EURUSD"), "corr-1")


if __name__ == "__main__":
    unittest.main()
