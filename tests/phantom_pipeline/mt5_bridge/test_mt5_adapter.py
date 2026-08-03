"""MT5Adapter translation tests — a fake `MetaTrader5` module double
stands in for the real, MT5-terminal-only package (ADR-008 §16), the same
"no live external dependency in unit tests" discipline every other stage
already established. Every test exercises `MT5Adapter`'s own translation
logic; nothing here talks to any real network, process, or terminal."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from phantom_pipeline.mt5_bridge.models import BrokerAcknowledgement, BrokerError, BrokerRequest, RequestKind
from phantom_pipeline.mt5_bridge.mt5_adapter import MT5Adapter
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


@dataclass
class _FakeTick:
    bid: float = 1.0995
    ask: float = 1.1005


@dataclass
class _FakePosition:
    ticket: int
    symbol: str = "EURUSD"
    type: int = 0  # ORDER_TYPE_BUY
    volume: float = 1.0
    sl: float = 0.0
    tp: float = 0.0


@dataclass
class _FakeOrderResult:
    retcode: int
    order: Optional[int] = None
    deal: Optional[int] = None
    comment: str = ""


@dataclass
class _FakeDeal:
    price: float = 1.1005
    volume: float = 1.0
    time: int = 1751000000


@dataclass
class _FakeTerminalInfo:
    connected: bool = True


@dataclass
class _FakeAccountInfo:
    equity: float = 10000.0


class _FakeMT5:
    """A minimal double of the small subset of `MetaTrader5`'s real
    surface `MT5Adapter` actually calls."""

    TRADE_ACTION_DEAL = "TRADE_ACTION_DEAL"
    TRADE_ACTION_SLTP = "TRADE_ACTION_SLTP"
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_RETCODE_DONE = 10009

    def __init__(self) -> None:
        self.initialize_result = True
        self.terminal_info_result: Optional[_FakeTerminalInfo] = _FakeTerminalInfo()
        self.account_info_result: Optional[_FakeAccountInfo] = _FakeAccountInfo()
        self.tick = _FakeTick()
        self.positions: Dict[int, _FakePosition] = {}
        self.open_position_tickets: Tuple[int, ...] = ()
        self.order_send_result: Optional[_FakeOrderResult] = _FakeOrderResult(retcode=self.TRADE_RETCODE_DONE, order=555)
        self.deals_by_ticket: Dict[int, List[_FakeDeal]] = {}
        self.last_error_value = ("no error",)
        self.shutdown_called = False
        self.sent_requests: List[dict] = []

    def initialize(self, **kwargs) -> bool:
        return self.initialize_result

    def shutdown(self) -> None:
        self.shutdown_called = True

    def terminal_info(self):
        return self.terminal_info_result

    def account_info(self):
        return self.account_info_result

    def symbol_info_tick(self, symbol: str):
        return self.tick

    def positions_get(self, ticket: Optional[int] = None):
        if ticket is not None:
            position = self.positions.get(ticket)
            return (position,) if position else ()
        return tuple(self.positions[t] for t in self.open_position_tickets)

    def order_send(self, request: dict):
        self.sent_requests.append(request)
        return self.order_send_result

    def history_deals_get(self, ticket: Optional[int] = None):
        return tuple(self.deals_by_ticket.get(ticket, ()))

    def last_error(self):
        return self.last_error_value


def _broker_request(
    request_kind: RequestKind = RequestKind.OPEN,
    direction: Optional[Direction] = Direction.UP,
    symbol: Optional[str] = "EURUSD",
    lot_size: Optional[float] = 0.5,
    position_id: Optional[str] = None,
    close_fraction: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
) -> BrokerRequest:
    return BrokerRequest(
        schema_version=1,
        execution_id="exec-1",
        trace_id="trace-1",
        request_kind=request_kind,
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_id=position_id,
        close_fraction=close_fraction,
        candidate_id="cand-1",
        timestamp=T0,
    )


class TestMT5AdapterConnection(unittest.TestCase):
    def test_connect_reflects_client_result(self):
        fake = _FakeMT5()
        fake.initialize_result = False
        adapter = MT5Adapter(mt5_module=fake)
        self.assertFalse(adapter.connect())

    def test_connect_success(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        self.assertTrue(adapter.connect())

    def test_disconnect_calls_shutdown(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        adapter.disconnect()
        self.assertTrue(fake.shutdown_called)

    def test_heartbeat_reflects_terminal_connected_flag(self):
        fake = _FakeMT5()
        fake.terminal_info_result = _FakeTerminalInfo(connected=False)
        adapter = MT5Adapter(mt5_module=fake)
        self.assertFalse(adapter.heartbeat())

    def test_heartbeat_false_when_terminal_info_missing(self):
        fake = _FakeMT5()
        fake.terminal_info_result = None
        adapter = MT5Adapter(mt5_module=fake)
        self.assertFalse(adapter.heartbeat())

    def test_lazy_import_raises_clear_error_without_injected_module_or_package(self):
        adapter = MT5Adapter()
        with self.assertRaises(RuntimeError):
            adapter.connect()


class TestMT5AdapterOpenOrder(unittest.TestCase):
    def test_open_buy_uses_ask_price(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(direction=Direction.UP)
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerAcknowledgement)
        self.assertEqual(fake.sent_requests[0]["price"], fake.tick.ask)
        self.assertEqual(fake.sent_requests[0]["type"], fake.ORDER_TYPE_BUY)

    def test_open_sell_uses_bid_price(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(direction=Direction.DOWN)
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerAcknowledgement)
        self.assertEqual(fake.sent_requests[0]["price"], fake.tick.bid)
        self.assertEqual(fake.sent_requests[0]["type"], fake.ORDER_TYPE_SELL)

    def test_unmappable_direction_is_broker_error_never_a_broker_call(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(direction=Direction.NEUTRAL)
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(fake.sent_requests, [])

    def test_missing_tick_is_broker_error(self):
        fake = _FakeMT5()
        fake.tick = None
        adapter = MT5Adapter(mt5_module=fake)
        response = adapter.send_request(_broker_request())
        self.assertIsInstance(response, BrokerError)

    def test_broker_rejection_translates_to_broker_error(self):
        fake = _FakeMT5()
        fake.order_send_result = _FakeOrderResult(retcode=10004, comment="requote")
        adapter = MT5Adapter(mt5_module=fake)
        response = adapter.send_request(_broker_request())
        self.assertIsInstance(response, BrokerError)
        self.assertIn("10004", response.reason)

    def test_order_send_none_translates_to_broker_error_with_last_error(self):
        fake = _FakeMT5()
        fake.order_send_result = None
        fake.last_error_value = (1, "no connection")
        adapter = MT5Adapter(mt5_module=fake)
        response = adapter.send_request(_broker_request())
        self.assertIsInstance(response, BrokerError)
        self.assertIn("no connection", response.reason)

    def test_stop_loss_and_take_profit_forwarded(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        adapter.send_request(_broker_request(stop_loss=1.0900, take_profit=1.1100))
        self.assertEqual(fake.sent_requests[0]["sl"], 1.0900)
        self.assertEqual(fake.sent_requests[0]["tp"], 1.1100)


class TestMT5AdapterAdjustAndClose(unittest.TestCase):
    def test_adjust_targets_existing_position(self):
        fake = _FakeMT5()
        fake.positions[42] = _FakePosition(ticket=42, sl=1.0900, tp=1.1200)
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(
            request_kind=RequestKind.ADJUST, symbol=None, direction=None, lot_size=None,
            position_id="42", stop_loss=1.0950,
        )
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerAcknowledgement)
        sent = fake.sent_requests[0]
        self.assertEqual(sent["position"], 42)
        self.assertEqual(sent["sl"], 1.0950)
        self.assertEqual(sent["tp"], 1.1200)  # unspecified take-profit preserved

    def test_adjust_unknown_position_is_broker_error(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(
            request_kind=RequestKind.ADJUST, symbol=None, direction=None, lot_size=None,
            position_id="999", stop_loss=1.0950,
        )
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerError)
        self.assertEqual(fake.sent_requests, [])

    def test_close_full_position_uses_opposite_type(self):
        fake = _FakeMT5()
        fake.positions[42] = _FakePosition(ticket=42, type=fake.ORDER_TYPE_BUY, volume=1.0)
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(
            request_kind=RequestKind.CLOSE, symbol=None, direction=None, lot_size=None,
            position_id="42", close_fraction=1.0,
        )
        response = adapter.send_request(request)
        self.assertIsInstance(response, BrokerAcknowledgement)
        sent = fake.sent_requests[0]
        self.assertEqual(sent["type"], fake.ORDER_TYPE_SELL)
        self.assertEqual(sent["volume"], 1.0)

    def test_close_partial_position_scales_volume(self):
        fake = _FakeMT5()
        fake.positions[42] = _FakePosition(ticket=42, type=fake.ORDER_TYPE_BUY, volume=2.0)
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request(
            request_kind=RequestKind.CLOSE, symbol=None, direction=None, lot_size=None,
            position_id="42", close_fraction=0.25,
        )
        adapter.send_request(request)
        self.assertEqual(fake.sent_requests[0]["volume"], 0.5)


class TestMT5AdapterPollingAndQueries(unittest.TestCase):
    def test_poll_execution_returns_none_for_unknown_execution_id(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        self.assertIsNone(adapter.poll_execution("never-submitted"))

    def test_poll_execution_returns_receipt_after_fill(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request()
        adapter.send_request(request)
        fake.deals_by_ticket[555] = [_FakeDeal(price=1.1006, volume=0.5)]
        receipt = adapter.poll_execution(request.execution_id)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.filled_price, 1.1006)
        self.assertEqual(receipt.trace_id, request.trace_id)

    def test_poll_execution_returns_none_before_fill_recorded(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        request = _broker_request()
        adapter.send_request(request)
        self.assertIsNone(adapter.poll_execution(request.execution_id))

    def test_query_open_position_ids(self):
        fake = _FakeMT5()
        fake.positions[1] = _FakePosition(ticket=1)
        fake.positions[2] = _FakePosition(ticket=2)
        fake.open_position_tickets = (1, 2)
        adapter = MT5Adapter(mt5_module=fake)
        self.assertEqual(adapter.query_open_position_ids(), ("1", "2"))

    def test_query_open_position_ids_empty(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        self.assertEqual(adapter.query_open_position_ids(), ())

    def test_query_account_equity(self):
        fake = _FakeMT5()
        adapter = MT5Adapter(mt5_module=fake)
        self.assertEqual(adapter.query_account_equity(), 10000.0)

    def test_query_account_equity_none_when_unavailable(self):
        fake = _FakeMT5()
        fake.account_info_result = None
        adapter = MT5Adapter(mt5_module=fake)
        self.assertIsNone(adapter.query_account_equity())


if __name__ == "__main__":
    unittest.main()
