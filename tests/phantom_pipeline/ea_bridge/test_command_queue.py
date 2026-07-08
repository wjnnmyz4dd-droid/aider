"""`CommandQueue` tests — idempotency, staleness, and fail-closed
behavior (`ADR-023` Hard Rules 4, 5, 7)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.ea_bridge.models import ExecutionReport, SCHEMA_VERSION
from tests.phantom_pipeline.ea_bridge._fixtures import T0, make_command, make_config, make_queue


def make_report(execution_id: str, success: bool = True, reason=None) -> ExecutionReport:
    return ExecutionReport(
        schema_version=SCHEMA_VERSION,
        execution_id=execution_id,
        magic_number=20260708,
        success=success,
        broker_ticket="ticket-1" if success else None,
        filled_price=1.1000 if success else None,
        filled_size=0.1 if success else None,
        reason=reason,
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
        self.assertEqual(reason, "bridge_not_ready")

    def test_duplicate_execution_id_rejected(self):
        queue = make_queue()
        self.assertIsNone(queue.enqueue(make_command(execution_id="exec-1"), is_ready=True))
        reason = queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        self.assertEqual(reason, "duplicate_command_id")

    def test_enqueue_refused_during_emergency_stop(self):
        queue = make_queue()
        queue.set_emergency_stop(True)
        reason = queue.enqueue(make_command(), is_ready=True)
        self.assertEqual(reason, "emergency_stop_active")


class TestPoll(unittest.TestCase):
    def test_poll_returns_pending_command(self):
        queue = make_queue()
        queue.enqueue(make_command(execution_id="exec-1", issued_at=T0), is_ready=True)
        delivered = queue.poll(T0 + timedelta(seconds=1))
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].execution_id, "exec-1")
        self.assertTrue(queue.is_delivered("exec-1"))

    def test_stale_command_is_dropped_not_delivered(self):
        config = make_config(command_ttl_seconds=5.0)
        queue = make_queue(config)
        queue.enqueue(make_command(execution_id="exec-1", issued_at=T0), is_ready=True)
        delivered = queue.poll(T0 + timedelta(seconds=10))
        self.assertEqual(delivered, ())
        self.assertFalse(queue.is_delivered("exec-1"))

    def test_poll_drains_pending_queue(self):
        queue = make_queue()
        queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        queue.poll(T0)
        second = queue.poll(T0)
        self.assertEqual(second, ())

    def test_poll_returns_nothing_during_emergency_stop(self):
        queue = make_queue()
        queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        queue.set_emergency_stop(True)
        self.assertEqual(queue.poll(T0), ())


class TestRecordResult(unittest.TestCase):
    def test_record_result_for_known_command_succeeds(self):
        queue = make_queue()
        queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        recorded = queue.record_result("exec-1", make_report("exec-1"))
        self.assertTrue(recorded)
        self.assertTrue(queue.is_executed("exec-1"))

    def test_duplicate_execution_report_is_a_noop(self):
        queue = make_queue()
        queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        first = queue.record_result("exec-1", make_report("exec-1", success=True))
        second = queue.record_result("exec-1", make_report("exec-1", success=False, reason="tampered"))
        self.assertTrue(first)
        self.assertFalse(second)
        # The original (first) result must survive -- a duplicate report
        # is never a second fill (ADR-023 Hard Rule 7).
        self.assertTrue(queue.result_for("exec-1").success)

    def test_result_for_unknown_execution_id_rejected(self):
        queue = make_queue()
        recorded = queue.record_result("never-issued", make_report("never-issued"))
        self.assertFalse(recorded)
        self.assertIsNone(queue.result_for("never-issued"))


if __name__ == "__main__":
    unittest.main()
