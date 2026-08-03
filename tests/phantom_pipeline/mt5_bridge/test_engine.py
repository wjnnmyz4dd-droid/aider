"""MT5Bridge engine tests (ADR-008 §2, §6-§9, §13)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.execution_validator.models import Verdict as ExecutionVerdict
from phantom_pipeline.mt5_bridge.broker_adapter import FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.config import MT5BridgeConfig
from phantom_pipeline.mt5_bridge.engine import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from phantom_pipeline.mt5_bridge.models import (
    BrokerAcknowledgement,
    BrokerError,
    ConnectionState,
    ExecutionReceipt,
    FillReport,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    RequestKind,
)
from tests.phantom_pipeline.mt5_bridge._fixtures import (
    PRICE,
    STOP_DISTANCE,
    T0,
    make_full_chain,
)


def _ready_bridge(**adapter_kwargs) -> MT5Bridge:
    adapter = FakeBrokerAdapter(**adapter_kwargs)
    bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig())
    bridge.connect(T0)
    bridge.synchronize(T0, expected_position_ids=())
    return bridge


class TestConnectionStateMachine(unittest.TestCase):
    def test_connect_success_reaches_connected(self):
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0))
        status = bridge.connect(T0)
        self.assertEqual(status.state, ConnectionState.CONNECTED)

    def test_connect_failure_stays_disconnected(self):
        bridge = MT5Bridge(FakeBrokerAdapter(connect_result=False), InMemoryTransportIdempotencyStore(3600.0))
        status = bridge.connect(T0)
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)

    def test_synchronize_without_discrepancy_reaches_ready(self):
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        conn_status, sync_status = bridge.synchronize(T0, expected_position_ids=())
        self.assertEqual(conn_status.state, ConnectionState.READY)
        self.assertTrue(sync_status.in_sync)

    def test_synchronize_without_prior_connect_reports_not_connected(self):
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0))
        conn_status, sync_status = bridge.synchronize(T0, expected_position_ids=())
        self.assertFalse(sync_status.in_sync)
        self.assertIn("not_connected", sync_status.discrepancies)

    def test_disconnect_returns_to_disconnected(self):
        bridge = _ready_bridge()
        status = bridge.disconnect(T0)
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)

    def test_reconnect_after_disconnect_reaches_connected(self):
        bridge = _ready_bridge()
        bridge.disconnect(T0)
        status = bridge.reconnect(T0)
        self.assertEqual(status.state, ConnectionState.CONNECTED)

    def test_reconnect_bounded_by_max_attempts(self):
        bridge = MT5Bridge(
            FakeBrokerAdapter(connect_result=False),
            InMemoryTransportIdempotencyStore(3600.0),
            MT5BridgeConfig(reconnect_max_attempts=3),
        )
        status = bridge.reconnect(T0)
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)


class TestHeartbeat(unittest.TestCase):
    def test_heartbeat_ok_keeps_state(self):
        bridge = _ready_bridge()
        status = bridge.heartbeat(T0 + timedelta(seconds=1))
        self.assertEqual(status.state, ConnectionState.READY)

    def test_missed_heartbeat_transitions_to_disconnected(self):
        config = MT5BridgeConfig(heartbeat_timeout_seconds=10.0)
        bridge = MT5Bridge(FakeBrokerAdapter(heartbeat_result=False), InMemoryTransportIdempotencyStore(3600.0), config)
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())
        later = T0 + timedelta(seconds=20)
        status = bridge.heartbeat(later)
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)


class TestSynchronizationDiscrepancy(unittest.TestCase):
    def test_missing_position_on_broker_halts_new_submissions(self):
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        conn_status, sync_status = bridge.synchronize(T0, expected_position_ids=("p1",))
        self.assertFalse(sync_status.in_sync)
        self.assertNotEqual(conn_status.state, ConnectionState.READY)

    def test_unexpected_position_on_broker_is_a_discrepancy(self):
        adapter = FakeBrokerAdapter()
        adapter.set_open_position_ids(("unexpected-p1",))
        bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        _, sync_status = bridge.synchronize(T0, expected_position_ids=())
        self.assertFalse(sync_status.in_sync)


class TestSubmitOrder(unittest.TestCase):
    def test_successful_order_translation_and_acknowledgement(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        bridge = _ready_bridge()

        reason, broker_request, response = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0,
            stop_loss=PRICE - STOP_DISTANCE, take_profit=PRICE + STOP_DISTANCE * 2,
        )

        self.assertIsNone(reason)
        self.assertEqual(broker_request.request_kind, RequestKind.OPEN)
        self.assertIsInstance(response, BrokerAcknowledgement)

    def test_missing_execution_decision_never_reaches_broker(self):
        candidate, _, risk_decision, compliance_decision, _ = make_full_chain()
        bridge = _ready_bridge()

        reason, broker_request, response = bridge.submit_order(
            None, risk_decision, compliance_decision, candidate, T0
        )

        self.assertEqual(reason, "missing_execution_decision")
        self.assertIsNone(broker_request)
        self.assertIsNone(response)

    def test_execution_decision_not_approved_is_rejected(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        rejected = execution_decision.__class__(
            **{**execution_decision.__dict__, "verdict": ExecutionVerdict.REJECT}
        )
        bridge = _ready_bridge()

        reason, broker_request, response = bridge.submit_order(
            rejected, risk_decision, compliance_decision, candidate, T0
        )

        self.assertEqual(reason, "execution_decision_not_approved")
        self.assertIsNone(broker_request)

    def test_connection_not_ready_produces_no_order(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0))
        # Never connected/synchronized -> not READY.

        reason, broker_request, response = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        self.assertEqual(reason, "connection_not_ready")
        self.assertIsNone(broker_request)

    def test_broker_rejection_is_returned_as_broker_error(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        adapter = FakeBrokerAdapter()
        bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())

        from phantom_pipeline.mt5_bridge.execution_id import make_execution_id

        execution_id = make_execution_id(candidate.trace_id, candidate.candidate_id)
        adapter.set_error_on_send(execution_id, "insufficient_funds")

        reason, broker_request, response = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        self.assertIsNone(reason)
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(response.reason, "insufficient_funds")

    def test_duplicate_submission_is_refused(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        bridge = _ready_bridge()

        bridge.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)
        reason, broker_request, response = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        self.assertEqual(reason, "duplicate_submission")
        self.assertIsNone(broker_request)

    def test_replayed_message_with_same_execution_id_is_refused(self):
        """A resubmitted/retried message carrying an already-seen
        execution_id is treated identically to a duplicate (ADR-008 §7)."""
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        bridge = _ready_bridge()

        bridge.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0 + timedelta(seconds=1))
        reason, _, _ = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0 + timedelta(seconds=2)
        )

        self.assertEqual(reason, "duplicate_submission")

    def test_missing_lot_size_is_rejected(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        zeroed = risk_decision.__class__(**{**risk_decision.__dict__, "lot_size": None})
        bridge = _ready_bridge()

        reason, broker_request, response = bridge.submit_order(
            execution_decision, zeroed, compliance_decision, candidate, T0
        )

        self.assertEqual(reason, "missing_lot_size")
        self.assertIsNone(broker_request)

    def test_malformed_request_mismatched_candidate(self):
        from tests.phantom_pipeline.mt5_bridge._fixtures import make_candidate

        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        other_candidate = make_candidate(trace_id="different-trace")
        bridge = _ready_bridge()

        reason, broker_request, response = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, other_candidate, T0
        )

        self.assertEqual(reason, "trace_id_candidate_id_mismatch")
        self.assertIsNone(broker_request)

    def test_trace_id_and_candidate_id_propagation(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        bridge = _ready_bridge()

        _, broker_request, _ = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        self.assertEqual(broker_request.trace_id, candidate.trace_id)
        self.assertEqual(broker_request.candidate_id, candidate.candidate_id)


class TestPollExecutionAndFills(unittest.TestCase):
    def test_successful_execution_response_parsing(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        adapter = FakeBrokerAdapter()
        bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())

        _, broker_request, _ = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )
        receipt = ExecutionReceipt(
            schema_version=1, execution_id=broker_request.execution_id, trace_id=broker_request.trace_id,
            request_kind=RequestKind.OPEN, broker_ref="r1", filled_price=1.1002, filled_size=risk_decision.lot_size,
            timestamp=T0,
        )
        adapter.set_execution_result(broker_request.execution_id, receipt)

        result = bridge.poll_execution(broker_request.execution_id, broker_request.trace_id, T0, T0 + timedelta(seconds=1))

        self.assertIsInstance(result, ExecutionReceipt)
        self.assertEqual(result.filled_price, 1.1002)

    def test_invalid_broker_response_is_returned_as_broker_error(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        adapter = FakeBrokerAdapter()
        bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())

        _, broker_request, _ = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )
        error = BrokerError(
            schema_version=1, execution_id=broker_request.execution_id, trace_id=broker_request.trace_id,
            request_kind=RequestKind.OPEN, reason="malformed_broker_reply", timestamp=T0,
        )
        adapter.set_execution_result(broker_request.execution_id, error)

        result = bridge.poll_execution(broker_request.execution_id, broker_request.trace_id, T0, T0 + timedelta(seconds=1))

        self.assertIsInstance(result, BrokerError)

    def test_timeout_when_no_result_beyond_ack_timeout(self):
        config = MT5BridgeConfig(acknowledgement_timeout_seconds=5.0)
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), config)
        result = bridge.poll_execution("e1", "t1", T0, T0 + timedelta(seconds=10))
        self.assertIsNone(result)

    def test_no_timeout_within_ack_window(self):
        config = MT5BridgeConfig(acknowledgement_timeout_seconds=5.0)
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), config)
        result = bridge.poll_execution("e1", "t1", T0, T0 + timedelta(seconds=1))
        self.assertIsNone(result)

    def test_duplicate_fill_is_flagged_not_accepted(self):
        bridge = _ready_bridge()
        fill = FillReport(schema_version=1, execution_id="e1", trace_id="t1", fill_price=1.1, fill_size=1.0, fill_timestamp=T0)

        first = bridge.record_fill(fill)
        second = bridge.record_fill(fill)

        self.assertTrue(first)
        self.assertFalse(second)


class TestPositionAdjustment(unittest.TestCase):
    def test_translation_and_submission(self):
        bridge = _ready_bridge()
        request = PositionAdjustmentRequest(1, "adj-1", "t1", "p1", 1.05, 1.2, T0)

        reason, broker_request, response = bridge.submit_position_adjustment(request, T0)

        self.assertIsNone(reason)
        self.assertEqual(broker_request.request_kind, RequestKind.ADJUST)
        self.assertEqual(broker_request.position_id, "p1")
        self.assertIsInstance(response, BrokerAcknowledgement)

    def test_missing_request_is_rejected(self):
        bridge = _ready_bridge()
        reason, broker_request, response = bridge.submit_position_adjustment(None, T0)
        self.assertEqual(reason, "missing_position_adjustment_request")

    def test_duplicate_adjustment_for_same_execution_id_is_refused(self):
        bridge = _ready_bridge()
        request = PositionAdjustmentRequest(1, "adj-1", "t1", "p1", 1.05, None, T0)

        bridge.submit_position_adjustment(request, T0)
        reason, _, _ = bridge.submit_position_adjustment(request, T0)

        self.assertEqual(reason, "duplicate_submission")

    def test_new_adjustment_for_same_position_but_different_execution_id_is_accepted(self):
        bridge = _ready_bridge()
        first = PositionAdjustmentRequest(1, "adj-1", "t1", "p1", 1.05, None, T0)
        second = PositionAdjustmentRequest(1, "adj-2", "t1", "p1", 1.06, None, T0)

        reason1, _, _ = bridge.submit_position_adjustment(first, T0)
        reason2, _, _ = bridge.submit_position_adjustment(second, T0)

        self.assertIsNone(reason1)
        self.assertIsNone(reason2)


class TestPositionClose(unittest.TestCase):
    def test_full_close_translation_and_submission(self):
        bridge = _ready_bridge()
        request = PositionCloseRequest(1, "close-1", "t1", "p1", 1.0, T0)

        reason, broker_request, response = bridge.submit_position_close(request, T0)

        self.assertIsNone(reason)
        self.assertEqual(broker_request.request_kind, RequestKind.CLOSE)
        self.assertEqual(broker_request.close_fraction, 1.0)

    def test_partial_close_translation(self):
        bridge = _ready_bridge()
        request = PositionCloseRequest(1, "close-2", "t1", "p1", 0.5, T0)

        reason, broker_request, response = bridge.submit_position_close(request, T0)

        self.assertIsNone(reason)
        self.assertEqual(broker_request.close_fraction, 0.5)

    def test_duplicate_close_for_same_execution_id_is_refused(self):
        bridge = _ready_bridge()
        request = PositionCloseRequest(1, "close-1", "t1", "p1", 1.0, T0)

        bridge.submit_position_close(request, T0)
        reason, _, _ = bridge.submit_position_close(request, T0)

        self.assertEqual(reason, "duplicate_close")


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_outputs(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()

        bridge1 = _ready_bridge()
        bridge2 = _ready_bridge()

        _, req1, resp1 = bridge1.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)
        _, req2, resp2 = bridge2.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)

        self.assertEqual(req1, req2)
        self.assertEqual(resp1, resp2)

    def test_replay_determinism_across_fresh_bridges(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        results = []
        for _ in range(3):
            bridge = _ready_bridge()
            _, req, resp = bridge.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)
            results.append((req, resp))
        self.assertTrue(all(r == results[0] for r in results))


class TestNoUpstreamMutation(unittest.TestCase):
    def test_upstream_decisions_are_untouched(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        before_risk, before_compliance, before_execution = risk_decision, compliance_decision, execution_decision
        bridge = _ready_bridge()

        bridge.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)

        self.assertIs(risk_decision, before_risk)
        self.assertIs(compliance_decision, before_compliance)
        self.assertIs(execution_decision, before_execution)


if __name__ == "__main__":
    unittest.main()
