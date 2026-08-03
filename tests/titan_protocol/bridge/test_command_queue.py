"""`CommandQueue` tests -- idempotency, staleness, and fail-closed
behavior (Phase 1)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.bridge.models import ErrorCode, ExecutionReport, SCHEMA_VERSION
from tests.titan_protocol.bridge._fixtures import T0, make_command, make_config, make_queue


def make_report(correlation_id: str, success: bool = True, error_code=None) -> ExecutionReport:
    return ExecutionReport(
        schema_version=SCHEMA_VERSION,
        correlation_id=correlation_id,
        magic_number=20260709,
        success=success,
        broker_ticket="ticket-1" if success else None,
        filled_price=1.1000 if success else None,
        filled_volume=0.1 if success else None,
        error_code=error_code,
        reported_at=T0,
    )


class TestEnqueue(unittest.TestCase):
    def test_enqueue_succeeds_when_ready(self):
        queue = make_queue()
        reason = queue.enqueue(make_command(), is_ready=True)
        self.assertIsNone(reason)

    def test_enqueue_fails_closed_when_not_ready(self):
        queue = make_queue()
        reason = queue.enqueue(make_command(), is_ready=False)
        self.assertEqual(reason, ErrorCode.BRIDGE_NOT_READY)

    def test_duplicate_correlation_id_rejected(self):
        queue = make_queue()
        self.assertIsNone(queue.enqueue(make_command(correlation_id="c1"), is_ready=True))
        reason = queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        self.assertEqual(reason, ErrorCode.DUPLICATE_CORRELATION_ID)

    def test_enqueue_refused_during_emergency_stop(self):
        queue = make_queue()
        queue.set_emergency_stop(True, "test", T0)
        reason = queue.enqueue(make_command(), is_ready=True)
        self.assertEqual(reason, ErrorCode.EMERGENCY_STOP_ACTIVE)


class TestPoll(unittest.TestCase):
    def test_poll_returns_pending_command(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        delivered = queue.poll(T0 + timedelta(seconds=1))
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].correlation_id, "c1")
        self.assertTrue(queue.is_delivered("c1"))

    def test_stale_command_is_dropped_not_delivered(self):
        config = make_config(command_ttl_seconds=5.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        delivered = queue.poll(T0 + timedelta(seconds=10))
        self.assertEqual(delivered, ())
        self.assertFalse(queue.is_delivered("c1"))

    def test_poll_drains_pending_queue(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        queue.poll(T0)
        second = queue.poll(T0)
        self.assertEqual(second, ())

    def test_poll_returns_nothing_during_emergency_stop(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        queue.set_emergency_stop(True, "test", T0)
        self.assertEqual(queue.poll(T0), ())


class TestRecordResult(unittest.TestCase):
    def test_record_result_for_known_command_succeeds(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        recorded = queue.record_result("c1", make_report("c1"))
        self.assertTrue(recorded)
        self.assertTrue(queue.is_executed("c1"))

    def test_duplicate_execution_report_is_a_noop(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        first = queue.record_result("c1", make_report("c1", success=True))
        second = queue.record_result("c1", make_report("c1", success=False, error_code="TAMPERED"))
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(queue.result_for("c1").success)

    def test_result_for_unknown_correlation_id_rejected(self):
        queue = make_queue()
        recorded = queue.record_result("never-issued", make_report("never-issued"))
        self.assertFalse(recorded)
        self.assertIsNone(queue.result_for("never-issued"))

    def test_all_results_returns_every_recorded_report(self):
        queue = make_queue()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        queue.enqueue(make_command(correlation_id="c2"), is_ready=True)
        queue.record_result("c1", make_report("c1"))
        queue.record_result("c2", make_report("c2"))
        results = queue.all_results()
        self.assertEqual({r.correlation_id for r in results}, {"c1", "c2"})


class TestIsAbandoned(unittest.TestCase):
    """`is_abandoned()` -- the single atomic query
    `InFlightCommandRegistry.reconcile()` uses to distinguish "silently
    vanished, undelivered" from "still genuinely in flight," replacing an
    earlier version of this fix that composed `is_delivered()` with a
    separately-computed age (see this queue's own docstring for why that
    combination was unsafe: it let a genuinely delivered command be
    treated as abandoned once retention purged it, and it left an
    unguarded window between two independently-timed reads)."""

    def test_unknown_correlation_id_is_never_abandoned(self):
        queue = make_queue()
        self.assertFalse(queue.is_abandoned("never-submitted", T0))

    def test_enqueued_but_not_yet_stale_is_not_abandoned(self):
        config = make_config(command_ttl_seconds=15.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        self.assertFalse(queue.is_abandoned("c1", T0 + timedelta(seconds=10)))

    def test_undelivered_and_past_ttl_is_abandoned(self):
        config = make_config(command_ttl_seconds=15.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        self.assertTrue(queue.is_abandoned("c1", T0 + timedelta(seconds=15.1)))

    def test_delivered_command_is_never_abandoned_no_matter_how_stale(self):
        """Production-readiness requirement: the registry must not
        release a delivered command merely because it aged out of the
        queue's own staleness window -- the reservation belongs to
        execution/rejection reconciliation from here on."""
        config = make_config(command_ttl_seconds=15.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        delivered = queue.poll(T0 + timedelta(seconds=5))
        self.assertEqual(len(delivered), 1)
        self.assertFalse(queue.is_abandoned("c1", T0 + timedelta(seconds=999)))

    def test_exactly_at_ttl_boundary_is_not_yet_abandoned(self):
        """poll()'s own staleness check is `age > command_ttl_seconds`
        (strictly greater) -- is_abandoned() must agree exactly, so a
        command still deliverable via poll() is never independently
        flagged abandoned by this method."""
        config = make_config(command_ttl_seconds=15.0)
        queue = make_queue(config)
        queue.enqueue(make_command(correlation_id="c1", issued_at=T0), is_ready=True)
        self.assertFalse(queue.is_abandoned("c1", T0 + timedelta(seconds=15.0)))


class TestIsAbandonedConcurrencySafety(unittest.TestCase):
    """Production-readiness requirement: the delivery check and queue
    expiry must be race-safe -- a poll() landing at nearly the same
    moment as an abandonment decision must never result in both a
    released reservation AND a live delivery for the same
    correlation_id, regardless of which order the two threads'
    operations actually interleave in.

    Deliberately races two *different* `now` readings, not the same one:
    Runtime's live-cycle loop and the Bridge's request-handling threads
    each call their own clock independently in production
    (`deployment_windows/start.py`'s `_utc_now()`, called separately by
    each), so a `poll()` call and a concurrent `is_abandoned()` call can
    plausibly disagree about whether a command is stale, by fractions of
    a second, purely due to when each thread happened to read the clock
    -- not because either individually miscomputed anything. `poll_now`
    is chosen just under `command_ttl_seconds` (poll() would, in
    isolation, still deliver) and `abandon_now` just over it
    (is_abandoned() would, in isolation, still conclude abandonment) --
    exactly the disagreement window a genuinely delivered-vs-abandoned
    race requires; without the mutual-exclusion fix (`_abandoned_ids`
    also checked by `poll()`), whichever thread's check ran second would
    contradict the other's already-committed decision."""

    def test_concurrent_poll_and_is_abandoned_never_both_succeed_for_the_same_correlation_id(self):
        import threading

        ttl = 15.0
        config = make_config(command_ttl_seconds=ttl)
        poll_now = T0 + timedelta(seconds=ttl - 0.001)  # poll() alone would deliver
        abandon_now = T0 + timedelta(seconds=ttl + 0.001)  # is_abandoned() alone would abandon
        iterations = 500
        violations = []
        barrier = threading.Barrier(2)

        for i in range(iterations):
            queue = make_queue(config)
            correlation_id = f"c{i}"
            queue.enqueue(make_command(correlation_id=correlation_id, issued_at=T0), is_ready=True)
            poll_result = {}
            abandoned_result = {}

            def do_poll():
                barrier.wait()
                poll_result["delivered"] = len(queue.poll(poll_now)) == 1

            def do_check():
                barrier.wait()
                abandoned_result["abandoned"] = queue.is_abandoned(correlation_id, abandon_now)

            t1 = threading.Thread(target=do_poll)
            t2 = threading.Thread(target=do_check)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Whichever order the two threads' critical sections actually
            # ran in, the two facts must never both hold: a command
            # cannot be simultaneously delivered (still live, reserved)
            # AND independently declared abandoned.
            if poll_result["delivered"] and abandoned_result["abandoned"]:
                violations.append(i)

        self.assertEqual(violations, [], f"is_abandoned() and a genuine delivery were both true for {len(violations)}/{iterations} runs")


if __name__ == "__main__":
    unittest.main()
