"""MT5-Bridge-only metrics surface (ADR-008 §12) — export-only,
additive, zero effect on returned outputs."""

from __future__ import annotations

import unittest

from phantom_pipeline.mt5_bridge.broker_adapter import FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.config import MT5BridgeConfig
from phantom_pipeline.mt5_bridge.engine import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from phantom_pipeline.mt5_bridge.metrics import MT5BridgeMetrics
from tests.phantom_pipeline.mt5_bridge._fixtures import T0, make_full_chain


class TestMT5BridgeMetrics(unittest.TestCase):
    def test_reconnect_count_increments(self):
        metrics = MT5BridgeMetrics()
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig(), metrics=metrics)
        bridge.connect(T0)
        bridge.disconnect(T0)

        bridge.reconnect(T0)

        self.assertEqual(metrics.reconnect_count, 1)

    def test_heartbeat_status_recorded(self):
        metrics = MT5BridgeMetrics()
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig(), metrics=metrics)
        bridge.connect(T0)

        bridge.heartbeat(T0)

        self.assertEqual(metrics.heartbeat_status.get("ok"), 1)

    def test_broker_reject_count_increments(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()
        metrics = MT5BridgeMetrics()
        adapter = FakeBrokerAdapter()
        bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig(), metrics=metrics)
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())

        from phantom_pipeline.mt5_bridge.execution_id import make_execution_id

        execution_id = make_execution_id(candidate.trace_id, candidate.candidate_id)
        adapter.set_error_on_send(execution_id, "rejected")

        bridge.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)

        self.assertEqual(metrics.broker_reject_count, 1)

    def test_phantom_side_reject_count_increments(self):
        candidate, _, risk_decision, compliance_decision, _ = make_full_chain()
        metrics = MT5BridgeMetrics()
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig(), metrics=metrics)
        bridge.connect(T0)
        bridge.synchronize(T0, expected_position_ids=())

        bridge.submit_order(None, risk_decision, compliance_decision, candidate, T0)

        self.assertEqual(metrics.phantom_side_reject_count, 1)

    def test_synchronization_status_recorded(self):
        metrics = MT5BridgeMetrics()
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig(), metrics=metrics)
        bridge.connect(T0)

        bridge.synchronize(T0, expected_position_ids=())

        self.assertEqual(metrics.synchronization_status.get("in_sync"), 1)

    def test_timeout_count_increments(self):
        config = MT5BridgeConfig(acknowledgement_timeout_seconds=1.0)
        metrics = MT5BridgeMetrics()
        bridge = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), config, metrics=metrics)

        from datetime import timedelta

        bridge.poll_execution("e1", "t1", T0, T0 + timedelta(seconds=5))

        self.assertEqual(metrics.timeout_count, 1)

    def test_recording_metrics_never_alters_returned_outputs(self):
        candidate, _, risk_decision, compliance_decision, execution_decision = make_full_chain()

        bridge_no_metrics = MT5Bridge(FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig())
        bridge_no_metrics.connect(T0)
        bridge_no_metrics.synchronize(T0, expected_position_ids=())
        _, req1, resp1 = bridge_no_metrics.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)

        bridge_with_metrics = MT5Bridge(
            FakeBrokerAdapter(), InMemoryTransportIdempotencyStore(3600.0), MT5BridgeConfig(), metrics=MT5BridgeMetrics()
        )
        bridge_with_metrics.connect(T0)
        bridge_with_metrics.synchronize(T0, expected_position_ids=())
        _, req2, resp2 = bridge_with_metrics.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)

        self.assertEqual(req1, req2)
        self.assertEqual(resp1, resp2)


if __name__ == "__main__":
    unittest.main()
