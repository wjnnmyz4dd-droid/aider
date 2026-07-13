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


if __name__ == "__main__":
    unittest.main()
