"""`EABrokerAdapter` tests — the `BrokerAdapter` ABC implementation
backed by the EA command relay (`ADR-023` §2, Hard Rule 2)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.ea_bridge.broker_adapter import EABrokerAdapter, command_from_broker_request
from phantom_pipeline.ea_bridge.command_queue import CommandQueue
from phantom_pipeline.ea_bridge.models import ExecutionReport, SCHEMA_VERSION
from phantom_pipeline.mt5_bridge import BrokerAdapter
from phantom_pipeline.mt5_bridge.models import BrokerAcknowledgement, BrokerError, BrokerRequest, RequestKind
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.ea_bridge._fixtures import T0, make_config


def make_broker_request(
    execution_id: str = "exec-1",
    symbol: str = "EURUSD",
    lot_size: float = 0.1,
    stop_loss=1.0950,
    take_profit=1.1100,
) -> BrokerRequest:
    return BrokerRequest(
        schema_version=1,
        execution_id=execution_id,
        trace_id="trace-1",
        request_kind=RequestKind.OPEN,
        symbol=symbol,
        direction=Direction.UP,
        lot_size=lot_size,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_id=None,
        close_fraction=None,
        candidate_id="cand-1",
        timestamp=T0,
    )


def make_adapter(config=None, now=T0):
    config = config or make_config()
    queue = CommandQueue(config)
    return EABrokerAdapter(queue, clock=lambda: now, config=config), queue


class TestIsBrokerAdapterSubclass(unittest.TestCase):
    def test_ea_broker_adapter_satisfies_the_existing_abc(self):
        self.assertTrue(issubclass(EABrokerAdapter, BrokerAdapter))


class TestCommandFromBrokerRequest(unittest.TestCase):
    def test_is_a_direct_field_mapping(self):
        request = make_broker_request()
        command = command_from_broker_request(request, magic_number=20260708, max_slippage_points=20, now=T0)
        self.assertEqual(command.execution_id, request.execution_id)
        self.assertEqual(command.trace_id, request.trace_id)
        self.assertEqual(command.symbol, request.symbol)
        self.assertEqual(command.lot_size, request.lot_size)
        self.assertEqual(command.stop_loss, request.stop_loss)
        self.assertEqual(command.take_profit, request.take_profit)
        self.assertEqual(command.magic_number, 20260708)


class TestConnectDisconnectHeartbeat(unittest.TestCase):
    def test_connect_is_always_true(self):
        adapter, _ = make_adapter()
        self.assertTrue(adapter.connect())

    def test_heartbeat_false_before_any_heartbeat_recorded(self):
        adapter, _ = make_adapter()
        self.assertFalse(adapter.heartbeat())

    def test_heartbeat_true_within_timeout(self):
        config = make_config(heartbeat_timeout_seconds=30.0)
        adapter, _ = make_adapter(config, now=T0 + timedelta(seconds=10))
        adapter.record_heartbeat(T0)
        self.assertTrue(adapter.heartbeat())

    def test_heartbeat_false_outside_timeout(self):
        config = make_config(heartbeat_timeout_seconds=30.0)
        adapter, _ = make_adapter(config, now=T0 + timedelta(seconds=60))
        adapter.record_heartbeat(T0)
        self.assertFalse(adapter.heartbeat())

    def test_disconnect_clears_heartbeat(self):
        adapter, _ = make_adapter()
        adapter.record_heartbeat(T0)
        adapter.disconnect()
        self.assertFalse(adapter.heartbeat())


class TestSendRequest(unittest.TestCase):
    def test_send_request_acknowledged_when_bridge_ready(self):
        adapter, _ = make_adapter(now=T0)
        adapter.record_heartbeat(T0)
        response = adapter.send_request(make_broker_request())
        self.assertIsInstance(response, BrokerAcknowledgement)

    def test_send_request_rejected_when_no_heartbeat(self):
        adapter, _ = make_adapter()
        response = adapter.send_request(make_broker_request())
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(response.reason, "bridge_not_ready")

    def test_send_request_rejects_disallowed_symbol_before_enqueue(self):
        adapter, queue = make_adapter()
        adapter.record_heartbeat(T0)
        response = adapter.send_request(make_broker_request(symbol="XAUUSD"))
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(response.reason, "symbol_not_allowed")
        self.assertIsNone(queue.command_for("exec-1"))

    def test_send_request_rejects_excess_volume(self):
        config = make_config(max_lot_size=1.0)
        adapter, _ = make_adapter(config)
        adapter.record_heartbeat(T0)
        response = adapter.send_request(make_broker_request(lot_size=5.0))
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(response.reason, "volume_exceeds_max")

    def test_send_request_rejects_invalid_stop_loss(self):
        adapter, _ = make_adapter()
        adapter.record_heartbeat(T0)
        response = adapter.send_request(make_broker_request(stop_loss=-1.0))
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(response.reason, "invalid_stop_loss")

    def test_duplicate_execution_id_rejected_by_underlying_queue(self):
        adapter, _ = make_adapter()
        adapter.record_heartbeat(T0)
        adapter.send_request(make_broker_request(execution_id="exec-dup"))
        response = adapter.send_request(make_broker_request(execution_id="exec-dup"))
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(response.reason, "duplicate_command_id")


class TestPollExecution(unittest.TestCase):
    def test_returns_none_when_no_result_yet(self):
        adapter, _ = make_adapter()
        adapter.record_heartbeat(T0)
        adapter.send_request(make_broker_request(execution_id="exec-1"))
        self.assertIsNone(adapter.poll_execution("exec-1"))

    def test_returns_none_for_unknown_execution_id(self):
        adapter, _ = make_adapter()
        self.assertIsNone(adapter.poll_execution("never-sent"))

    def test_returns_receipt_on_success(self):
        adapter, queue = make_adapter()
        adapter.record_heartbeat(T0)
        adapter.send_request(make_broker_request(execution_id="exec-1"))
        queue.record_result(
            "exec-1",
            ExecutionReport(
                schema_version=SCHEMA_VERSION, execution_id="exec-1", magic_number=20260708,
                success=True, broker_ticket="t-1", filled_price=1.1005, filled_size=0.1,
                reason=None, reported_at=T0,
            ),
        )
        receipt = adapter.poll_execution("exec-1")
        self.assertEqual(receipt.broker_ref, "t-1")
        self.assertEqual(receipt.filled_price, 1.1005)

    def test_returns_broker_error_on_failure(self):
        adapter, queue = make_adapter()
        adapter.record_heartbeat(T0)
        adapter.send_request(make_broker_request(execution_id="exec-1"))
        queue.record_result(
            "exec-1",
            ExecutionReport(
                schema_version=SCHEMA_VERSION, execution_id="exec-1", magic_number=20260708,
                success=False, broker_ticket=None, filled_price=None, filled_size=None,
                reason="requote", reported_at=T0,
            ),
        )
        result = adapter.poll_execution("exec-1")
        self.assertIsInstance(result, BrokerError)
        self.assertEqual(result.reason, "requote")


class TestQueryMethods(unittest.TestCase):
    def test_query_account_equity_none_until_reported(self):
        adapter, _ = make_adapter()
        self.assertIsNone(adapter.query_account_equity())
        adapter.record_account_equity(9000.0)
        self.assertEqual(adapter.query_account_equity(), 9000.0)

    def test_query_open_position_ids_empty_until_reported(self):
        adapter, _ = make_adapter()
        self.assertEqual(adapter.query_open_position_ids(), ())
        adapter.record_open_position_ids(("p1", "p2"))
        self.assertEqual(adapter.query_open_position_ids(), ("p1", "p2"))


if __name__ == "__main__":
    unittest.main()
