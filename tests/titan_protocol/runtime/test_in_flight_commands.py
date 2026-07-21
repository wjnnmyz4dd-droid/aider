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


class TestExpireStalePositionConfirmations(unittest.TestCase):
    """Production-readiness hardening: a resolved pair waiting for a
    confirming /bridge/positions snapshot must not wait forever if
    positions reporting has permanently stopped -- see
    in_flight_commands.py's own docstring for why releasing the pair
    fail-safe here preserves, rather than weakens, capital preservation
    (Compliance's independent max_positions_per_pair check remains the
    real duplicate-position guard)."""

    def test_normal_confirmation_before_timeout_is_unaffected(self):
        """The ordinary, healthy path: confirm_position_report() releases
        the pair long before the timeout would ever apply -- the timeout
        mechanism must never interfere with normal operation."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        confirmed = registry.confirm_position_report(_NOW + timedelta(seconds=2))
        self.assertEqual(confirmed, 1)
        timed_out = registry.expire_stale_position_confirmations(_NOW + timedelta(seconds=3))
        self.assertEqual(timed_out, ())
        self.assertEqual(registry.position_confirmation_timeout_count(), 0)

    def test_confirmation_just_before_timeout_still_succeeds(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        just_before_timeout = _NOW + timedelta(seconds=119.999)
        # A caller would normally call expire_stale_position_confirmations()
        # every cycle -- at 119.999s it must not have released the pair yet.
        timed_out = registry.expire_stale_position_confirmations(just_before_timeout)
        self.assertEqual(timed_out, ())
        self.assertTrue(registry.is_awaiting_position_confirmation("EURUSD"))
        # The snapshot then arrives, just in time.
        confirmed = registry.confirm_position_report(just_before_timeout)
        self.assertEqual(confirmed, 1)
        self.assertFalse(registry.has_unresolved("EURUSD", just_before_timeout))

    def test_exactly_at_timeout_boundary_is_not_yet_released(self):
        """Mirrors CommandQueue.is_abandoned()'s own boundary convention:
        `waited_seconds > timeout`, not `>=` -- exactly at the boundary
        is still within the allowed wait."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        at_boundary = _NOW + timedelta(seconds=120.0)
        timed_out = registry.expire_stale_position_confirmations(at_boundary)
        self.assertEqual(timed_out, ())
        self.assertTrue(registry.is_awaiting_position_confirmation("EURUSD"))

    def test_confirmation_after_timeout_has_already_been_released(self):
        """Once expire_stale_position_confirmations() has released a
        pair, a *later*-arriving positions snapshot naming that pair no
        longer confirms anything for it (there is nothing left to
        confirm) -- it simply becomes eligible for a fresh submission,
        exactly like any other freed pair."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        past_timeout = _NOW + timedelta(seconds=120.001)
        timed_out = registry.expire_stale_position_confirmations(past_timeout)
        self.assertEqual(timed_out, (("EURUSD", "corr-1", 120.001),))
        self.assertFalse(registry.is_awaiting_position_confirmation("EURUSD"))
        self.assertFalse(registry.has_unresolved("EURUSD", past_timeout))
        # A very late snapshot no longer has anything to confirm for this pair.
        confirmed = registry.confirm_position_report(past_timeout + timedelta(seconds=1))
        self.assertEqual(confirmed, 0)

    def test_permanent_loss_of_position_reporting_eventually_releases_the_pair(self):
        """Simulates /bridge/positions reporting having stopped entirely:
        confirm_position_report() is never called again after resolution
        -- only expire_stale_position_confirmations() runs every cycle,
        as start.py's live-cycle loop does. The pair must stay blocked
        until the timeout, then be released -- never sooner, never
        forever."""
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        for elapsed in (10, 30, 60, 90, 119):
            timed_out = registry.expire_stale_position_confirmations(_NOW + timedelta(seconds=elapsed))
            self.assertEqual(timed_out, (), f"must not release before the timeout (elapsed={elapsed}s)")
            self.assertTrue(registry.has_unresolved("EURUSD", _NOW + timedelta(seconds=elapsed)))
        released_at = _NOW + timedelta(seconds=121)
        timed_out = registry.expire_stale_position_confirmations(released_at)
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(timed_out[0][0], "EURUSD")
        self.assertEqual(timed_out[0][1], "corr-1")
        self.assertFalse(registry.has_unresolved("EURUSD", released_at))
        self.assertEqual(registry.position_confirmation_timeout_count(), 1)

    def test_multiple_simultaneous_confirmations_only_stale_ones_released(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        later = _NOW + timedelta(seconds=50)
        registry.record_submission("GBPUSD", "corr-2", later)
        registry.reconcile(later, is_resolved=lambda cid: True)
        registry.record_submission("USDJPY", "corr-3", later)
        registry.reconcile(later, is_resolved=lambda cid: True)
        self.assertEqual(registry.awaiting_position_confirmation_count(), 3)

        # EURUSD resolved at _NOW (150s ago from `check_at`), past timeout.
        # GBPUSD/USDJPY resolved at `later` (100s ago from `check_at`), not yet.
        check_at = _NOW + timedelta(seconds=150)
        timed_out = registry.expire_stale_position_confirmations(check_at)
        released_pairs = {entry[0] for entry in timed_out}
        self.assertEqual(released_pairs, {"EURUSD"})
        self.assertFalse(registry.is_awaiting_position_confirmation("EURUSD"))
        self.assertTrue(registry.is_awaiting_position_confirmation("GBPUSD"))
        self.assertTrue(registry.is_awaiting_position_confirmation("USDJPY"))
        self.assertEqual(registry.position_confirmation_timeout_count(), 1)

        # Now advance far enough that GBPUSD and USDJPY both time out too,
        # in the same call -- multiple simultaneous releases.
        much_later = _NOW + timedelta(seconds=50 + 121)
        timed_out_2 = registry.expire_stale_position_confirmations(much_later)
        released_pairs_2 = {entry[0] for entry in timed_out_2}
        self.assertEqual(released_pairs_2, {"GBPUSD", "USDJPY"})
        self.assertEqual(registry.awaiting_position_confirmation_count(), 0)
        self.assertEqual(registry.position_confirmation_timeout_count(), 3)

    def test_default_timeout_is_120_seconds(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: True)
        self.assertEqual(registry.expire_stale_position_confirmations(_NOW + timedelta(seconds=120)), ())
        released = registry.expire_stale_position_confirmations(_NOW + timedelta(seconds=120.001))
        self.assertEqual(len(released), 1)


class TestSnapshotForPersistenceAndRestore(unittest.TestCase):
    """Restart-safe persistence (production-readiness hardening): proves
    snapshot_for_persistence()/restore() round-trip the pair-level block
    correctly, that an abandoned/resolved-and-confirmed pair is never
    included in a snapshot (so persistence structurally cannot resurrect
    it), and that restore() preserves original timestamps rather than
    resetting the TTL/timeout clock on every restart."""

    def test_snapshot_includes_in_flight_and_awaiting_confirmation_entries(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.record_submission("GBPUSD", "corr-2", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: cid == "corr-2")
        snapshot = registry.snapshot_for_persistence()
        by_pair = {entry.pair: entry for entry in snapshot}
        self.assertEqual(by_pair["EURUSD"].state, "in_flight")
        self.assertEqual(by_pair["EURUSD"].correlation_id, "corr-1")
        self.assertEqual(by_pair["EURUSD"].timestamp, _NOW)
        self.assertEqual(by_pair["GBPUSD"].state, "awaiting_position_confirmation")
        self.assertEqual(by_pair["GBPUSD"].correlation_id, "corr-2")
        self.assertEqual(by_pair["GBPUSD"].timestamp, _NOW)

    def test_abandoned_pair_is_never_in_the_snapshot(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: False, is_abandoned=lambda cid: True)
        snapshot = registry.snapshot_for_persistence()
        self.assertEqual(snapshot, ())

    def test_restore_reestablishes_blocking_using_original_timestamp(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        snapshot = registry.snapshot_for_persistence()

        restarted_registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        restart_time = _NOW + timedelta(seconds=60)
        restored_count = restarted_registry.restore(snapshot, restart_time)
        self.assertEqual(restored_count, 1)
        self.assertTrue(restarted_registry.has_unresolved("EURUSD", restart_time))
        self.assertEqual(restarted_registry.correlation_id_for("EURUSD"), "corr-1")
        # TTL keeps counting from the ORIGINAL submission time (_NOW), not
        # from restart_time -- at _NOW + 300s (240s after restart) it must
        # already be expired, not freshly-clocked from the restart.
        self.assertFalse(restarted_registry.has_unresolved("EURUSD", _NOW + timedelta(seconds=301)))

    def test_restore_skips_entries_already_past_their_own_timeout(self):
        registry = InFlightCommandRegistry(ttl_seconds=60.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        snapshot = registry.snapshot_for_persistence()

        restarted_registry = InFlightCommandRegistry(ttl_seconds=60.0)
        long_after_restart = _NOW + timedelta(seconds=500)  # already past the 60s ttl
        restored_count = restarted_registry.restore(snapshot, long_after_restart)
        self.assertEqual(restored_count, 0)
        self.assertFalse(restarted_registry.has_unresolved("EURUSD", long_after_restart))

    def test_restore_does_not_overwrite_an_already_tracked_pair(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        snapshot = registry.snapshot_for_persistence()

        live_registry = InFlightCommandRegistry(ttl_seconds=300.0)
        live_registry.record_submission("EURUSD", "corr-live", _NOW + timedelta(seconds=10))
        restored_count = live_registry.restore(snapshot, _NOW + timedelta(seconds=10))
        self.assertEqual(restored_count, 0)
        self.assertEqual(live_registry.correlation_id_for("EURUSD"), "corr-live")

    def test_restore_of_multiple_simultaneous_unresolved_pairs(self):
        registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        registry.record_submission("EURUSD", "corr-1", _NOW)
        registry.record_submission("GBPUSD", "corr-2", _NOW)
        registry.record_submission("USDJPY", "corr-3", _NOW)
        registry.reconcile(_NOW, is_resolved=lambda cid: cid == "corr-3")
        snapshot = registry.snapshot_for_persistence()
        self.assertEqual(len(snapshot), 3)

        restarted_registry = InFlightCommandRegistry(ttl_seconds=300.0, position_confirmation_timeout_seconds=120.0)
        restart_time = _NOW + timedelta(seconds=5)
        restored_count = restarted_registry.restore(snapshot, restart_time)
        self.assertEqual(restored_count, 3)
        self.assertTrue(restarted_registry.has_unresolved("EURUSD", restart_time))
        self.assertTrue(restarted_registry.has_unresolved("GBPUSD", restart_time))
        self.assertTrue(restarted_registry.is_awaiting_position_confirmation("USDJPY"))


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
