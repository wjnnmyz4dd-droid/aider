"""Structured logging emission tests (ADR-008 §11)."""

from __future__ import annotations

import logging
import unittest

from phantom_pipeline.mt5_bridge.broker_adapter import FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.config import MT5BridgeConfig
from phantom_pipeline.mt5_bridge.engine import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from phantom_pipeline.mt5_bridge.logging_sink import logger
from tests.phantom_pipeline.mt5_bridge._fixtures import T0, make_full_chain


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestMT5BridgeLogging(unittest.TestCase):
    def setUp(self):
        self.handler = _CapturingHandler()
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        self.previous_propagate = logger.propagate
        logger.propagate = False

    def tearDown(self):
        logger.removeHandler(self.handler)
        logger.propagate = self.previous_propagate

    def _ready_bridge(self):
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig())
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())
        return bridge

    def test_submission_and_acknowledgement_are_logged_with_trace_and_execution_id(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        bridge = self._ready_bridge()
        self.handler.records.clear()

        _, broker_request, _ = bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        submission_records = [r for r in self.handler.records if r.msg == "mt5_bridge.submission"]
        ack_records = [r for r in self.handler.records if r.msg == "mt5_bridge.acknowledgement"]
        self.assertEqual(len(submission_records), 1)
        self.assertEqual(len(ack_records), 1)
        self.assertEqual(submission_records[0].execution_id, broker_request.execution_id)
        self.assertEqual(submission_records[0].trace_id, broker_request.trace_id)
        self.assertEqual(ack_records[0].execution_id, broker_request.execution_id)

    def test_phantom_side_reject_is_logged(self):
        candidate, _, risk_decision, compliance_decision, _ = make_full_chain()
        bridge = self._ready_bridge()
        self.handler.records.clear()

        bridge.submit_order(None, risk_decision, compliance_decision, candidate, T0)

        reject_records = [r for r in self.handler.records if r.msg == "mt5_bridge.phantom_side_reject"]
        self.assertEqual(len(reject_records), 1)
        self.assertEqual(reject_records[0].reason, "missing_execution_decision")

    def test_disconnect_is_logged(self):
        bridge = self._ready_bridge()
        self.handler.records.clear()

        bridge.disconnect(T0)

        disconnect_records = [r for r in self.handler.records if r.msg == "mt5_bridge.disconnect"]
        self.assertEqual(len(disconnect_records), 1)

    def test_synchronization_is_logged(self):
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0))
        bridge.connect(T0)
        self.handler.records.clear()

        bridge.synchronize(T0, expected_position_ids=())

        sync_records = [r for r in self.handler.records if r.msg == "mt5_bridge.synchronization"]
        self.assertEqual(len(sync_records), 1)

    def test_logging_never_alters_engine_output(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()

        logger.removeHandler(self.handler)
        silent_bridge = self._ready_bridge()
        _, req1, resp1 = silent_bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        logger.addHandler(self.handler)
        observed_bridge = self._ready_bridge()
        _, req2, resp2 = observed_bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, T0
        )

        self.assertEqual(req1, req2)
        self.assertEqual(resp1, resp2)


if __name__ == "__main__":
    unittest.main()
