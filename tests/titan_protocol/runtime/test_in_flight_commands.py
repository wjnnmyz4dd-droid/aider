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
        # Resolved, but has_unresolved() keeps blocking until a positions
        # snapshot confirms the post-execution state -- see
        # TestPostResolutionPositionConfirmation for that mechanism.
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))
        registry.confirm_position_report(_NOW + timedelta(seconds=1))
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
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))  # awaiting position confirmation
        self.assertTrue(registry.has_unresolved("GBPUSD", _NOW))  # still genuinely in flight
        self.assertEqual(registry.in_flight_count(), 1)
        registry.confirm_position_report(_NOW + timedelta(seconds=1))
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))


class TestResubmissionAfterResolution(unittest.TestCase):
    def test_pair_can_be_resubmitted_once_resolved(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        registry.confirm_position_report(_NOW + timedelta(seconds=1))  # post-execution snapshot observed
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


class TestPostResolutionPositionConfirmation(unittest.TestCase):
    """Closes the traced ExecutionReport-vs-PositionReport race: a
    resolved command must not immediately free its pair for resubmission
    -- has_unresolved() must keep blocking until a positions snapshot
    dated at or after the resolution moment has been observed."""

    def test_resolved_pair_still_blocked_until_position_report_confirms(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        dropped = registry.reconcile(_NOW, is_resolved=lambda cid: True)
        self.assertEqual(dropped, 1)
        # Resolved, but no positions snapshot confirmed yet -- still blocked.
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))
        self.assertTrue(registry.is_awaiting_position_confirmation("EURUSD"))
        self.assertEqual(registry.awaiting_position_confirmation_count(), 1)

    def test_stale_snapshot_older_than_resolution_does_not_confirm(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        stale_snapshot_at = _NOW - timedelta(seconds=5)  # taken before resolution
        confirmed = registry.confirm_position_report(stale_snapshot_at)
        self.assertEqual(confirmed, 0)
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))

    def test_fresh_snapshot_at_or_after_resolution_confirms_and_unblocks(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        fresh_snapshot_at = _NOW + timedelta(seconds=5)
        confirmed = registry.confirm_position_report(fresh_snapshot_at)
        self.assertEqual(confirmed, 1)
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))
        self.assertFalse(registry.is_awaiting_position_confirmation("EURUSD"))

    def test_none_snapshot_confirms_nothing(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        confirmed = registry.confirm_position_report(None)
        self.assertEqual(confirmed, 0)
        self.assertTrue(registry.has_unresolved("EURUSD", _NOW))

    def test_ttl_expiry_never_enters_awaiting_confirmation(self):
        """A never-resolved (TTL-expired) command has no ExecutionReport
        to confirm against -- it must be immediately resubmittable, not
        gated on a positions snapshot that will never specifically
        correspond to it."""
        registry = InFlightCommandRegistry(ttl_seconds=60.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=61)
        dropped = registry.reconcile(later, is_resolved=lambda cid: False)
        self.assertEqual(dropped, 1)
        self.assertFalse(registry.has_unresolved("EURUSD", later))
        self.assertFalse(registry.is_awaiting_position_confirmation("EURUSD"))

    def test_record_submission_clears_any_stale_awaiting_confirmation(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        self.assertTrue(registry.is_awaiting_position_confirmation("EURUSD"))
        later = _NOW + timedelta(seconds=5)
        registry.confirm_position_report(later)  # releases it
        registry.record_submission("EURUSD", "corr-2", later)
        self.assertFalse(registry.is_awaiting_position_confirmation("EURUSD"))
        self.assertTrue(registry.has_unresolved("EURUSD", later))

    def test_different_pairs_confirmed_independently(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.record_submission("GBPUSD", "corr-2", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        self.assertEqual(registry.awaiting_position_confirmation_count(), 2)
        confirmed = registry.confirm_position_report(_NOW + timedelta(seconds=1))
        self.assertEqual(confirmed, 2)
        self.assertFalse(registry.has_unresolved("EURUSD", _NOW))
        self.assertFalse(registry.has_unresolved("GBPUSD", _NOW))


class TestUndeliveredCommandAbandonment(unittest.TestCase):
    """Fix for "the runtime never exits the failure loop": a command
    that silently expires in CommandQueue before the EA ever polls it
    must be dropped far sooner than the full ttl_seconds -- otherwise the
    pair stays blocked doing nothing until ttl_seconds elapses, even
    though the command was already abandoned long before that.

    `is_abandoned` is a single, caller-supplied callable (in production,
    `BridgeEngine.command_abandoned`, backed by `CommandQueue.
    is_abandoned()`'s own atomic delivered/stale check) -- this registry
    never computes delivery status or a grace-period age itself, exactly
    to avoid recomposing the same two-separately-timed-reads race that an
    earlier version of this fix had (see this module's own docstring)."""

    def test_abandoned_entry_is_dropped_before_full_ttl(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=16)  # nowhere near the 300s ttl
        dropped = registry.reconcile(later, is_resolved=lambda cid: False, is_abandoned=lambda cid: True)
        self.assertEqual(dropped, 1)
        self.assertFalse(registry.has_unresolved("EURUSD", later))
        self.assertFalse(registry.is_awaiting_position_confirmation("EURUSD"))

    def test_not_abandoned_entry_is_kept(self):
        """A command the EA actually received (is_abandoned() says False,
        per CommandQueue's own atomic check) keeps its full ttl_seconds
        -- it may simply be slow to execute or report back."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=16)
        dropped = registry.reconcile(later, is_resolved=lambda cid: False, is_abandoned=lambda cid: False)
        self.assertEqual(dropped, 0)
        self.assertTrue(registry.has_unresolved("EURUSD", later))

    def test_resolved_entry_takes_priority_over_abandonment(self):
        """A command that somehow resolved despite is_abandoned() saying
        True (e.g. a caller whose two signals raced) must still move to
        awaiting-position-confirmation, never be treated as abandoned --
        resolution is the stronger, more specific signal."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=16)
        dropped = registry.reconcile(later, is_resolved=lambda cid: True, is_abandoned=lambda cid: True)
        self.assertEqual(dropped, 1)
        self.assertTrue(registry.is_awaiting_position_confirmation("EURUSD"))

    def test_feature_disabled_by_default_preserves_prior_behavior(self):
        """is_abandoned defaults to None -- an entry waits out the full
        ttl_seconds regardless of delivery status, exactly as before this
        fix, unless a caller explicitly opts in."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        later = _NOW + timedelta(seconds=16)
        dropped = registry.reconcile(later, is_resolved=lambda cid: False)
        self.assertEqual(dropped, 0)
        self.assertTrue(registry.has_unresolved("EURUSD", later))


if __name__ == "__main__":
    unittest.main()
