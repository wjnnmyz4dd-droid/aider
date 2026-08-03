"""FakeBrokerAdapter sanity tests — the deterministic test double
standing in for real MT5 communication (ADR-008 §16)."""

from __future__ import annotations

import unittest

from phantom_pipeline.mt5_bridge.broker_adapter import FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.models import BrokerAcknowledgement, BrokerRequest, RequestKind
from tests.phantom_pipeline.mt5_bridge._fixtures import T0


class TestFakeBrokerAdapter(unittest.TestCase):
    def test_connect_reflects_configured_result(self):
        adapter = FakeBrokerAdapter(connect_result=False)
        self.assertFalse(adapter.connect())

    def test_heartbeat_reflects_configured_result(self):
        adapter = FakeBrokerAdapter(heartbeat_result=False)
        self.assertFalse(adapter.heartbeat())

    def test_send_request_returns_acknowledgement_by_default(self):
        adapter = FakeBrokerAdapter()
        request = BrokerRequest(
            schema_version=1, execution_id="e1", trace_id="t1", request_kind=RequestKind.OPEN,
            symbol="EURUSD", direction=None, lot_size=1.0, stop_loss=None, take_profit=None,
            position_id=None, close_fraction=None, candidate_id="c1", timestamp=T0,
        )
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerAcknowledgement)

    def test_query_account_equity_returns_configured_value(self):
        adapter = FakeBrokerAdapter(account_equity=5000.0)
        self.assertEqual(adapter.query_account_equity(), 5000.0)

    def test_query_open_position_ids_returns_configured_value(self):
        adapter = FakeBrokerAdapter(expected_position_ids=("p1", "p2"))
        self.assertEqual(adapter.query_open_position_ids(), ("p1", "p2"))


if __name__ == "__main__":
    unittest.main()
