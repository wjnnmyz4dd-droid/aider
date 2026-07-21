"""`BridgeEngine` tests -- telemetry, command submission/relay, drift
detection, and emergency-stop control (Phase 1)."""

from __future__ import annotations

import logging
import unittest
from datetime import timedelta

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.metrics import BridgeMetrics
from titan_protocol.bridge.models import (
    AccountState,
    CommandKind,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PendingOrderReport,
    PositionDirection,
    PositionReport,
    SCHEMA_VERSION,
    TradeTransactionReport,
)
from tests.titan_protocol.bridge._fixtures import T0, make_command, make_config


def make_engine(config=None):
    config = config or make_config()
    queue = CommandQueue(config)
    health = ConnectionHealth(config, clock=lambda: T0)
    metrics = BridgeMetrics()
    engine = BridgeEngine(config, queue, health, clock=lambda: T0, metrics=metrics)
    return engine, queue, health, metrics


class TestHandleHeartbeat(unittest.TestCase):
    def test_records_heartbeat_and_increments_metric(self):
        engine, _, health, metrics = make_engine()
        message = HeartbeatMessage(
            schema_version=SCHEMA_VERSION, magic_number=20260709, account_login=1,
            terminal_connected=True, received_at=T0,
        )
        engine.handle_heartbeat(message)
        self.assertEqual(metrics.heartbeat_count, 1)
        self.assertTrue(health.is_ready())
        self.assertTrue(engine.is_connection_healthy)


class TestHandleAccountState(unittest.TestCase):
    def test_stores_latest_account_state(self):
        engine, _, _, metrics = make_engine()
        state = AccountState(
            schema_version=SCHEMA_VERSION, magic_number=20260709, balance=10000.0, equity=10500.0,
            margin=100.0, free_margin=10400.0, currency="USD", leverage=100, received_at=T0,
        )
        engine.handle_account_state(state)
        self.assertEqual(engine.latest_account_state.equity, 10500.0)
        self.assertEqual(metrics.account_update_count, 1)


class TestHandlePositionsAndOrders(unittest.TestCase):
    def test_positions_stored(self):
        engine, _, _, metrics = make_engine()
        positions = (
            PositionReport(
                schema_version=SCHEMA_VERSION, position_id="p1", symbol="EURUSD",
                direction=PositionDirection.BUY, volume=0.1, open_price=1.10, stop_loss=1.09,
                take_profit=1.12, unrealized_pnl=5.0, magic_number=20260709, received_at=T0,
            ),
        )
        engine.handle_positions(positions, T0)
        self.assertEqual(engine.latest_positions[0].position_id, "p1")
        self.assertEqual(metrics.position_update_count, 1)
        self.assertEqual(engine.last_positions_received_at, T0)

    def test_last_positions_received_at_set_even_when_empty(self):
        engine, _, _, _ = make_engine()
        self.assertIsNone(engine.last_positions_received_at)
        engine.handle_positions((), T0)
        self.assertEqual(engine.last_positions_received_at, T0)

    def test_pending_orders_stored(self):
        engine, _, _, metrics = make_engine()
        orders = (
            PendingOrderReport(
                schema_version=SCHEMA_VERSION, order_id="o1", symbol="EURUSD", order_type="3",
                volume=0.1, price=1.08, stop_loss=None, take_profit=None,
                magic_number=20260709, received_at=T0,
            ),
        )
        engine.handle_pending_orders(orders)
        self.assertEqual(engine.latest_pending_orders[0].order_id, "o1")
        self.assertEqual(metrics.pending_order_update_count, 1)


class TestCommandResolved(unittest.TestCase):
    """command_resolved() -- the one additive passthrough BridgeEngine
    gained so Runtime's InFlightCommandRegistry can ask whether a
    correlation_id it submitted has reached a terminal state, without
    reaching into this engine's private CommandQueue directly."""

    def test_unknown_correlation_id_is_not_resolved(self):
        engine, _, _, _ = make_engine()
        self.assertFalse(engine.command_resolved("never-submitted"))

    def test_submitted_but_not_reported_is_not_resolved(self):
        engine, queue, _, _ = make_engine()
        queue.enqueue(make_command(correlation_id="corr-1"), is_ready=True)
        self.assertFalse(engine.command_resolved("corr-1"))

    def test_execution_report_marks_it_resolved(self):
        engine, queue, _, _ = make_engine()
        queue.enqueue(make_command(correlation_id="corr-1"), is_ready=True)
        report = ExecutionReport(
            schema_version=SCHEMA_VERSION, correlation_id="corr-1", magic_number=20260709,
            success=True, broker_ticket="T1", filled_price=1.10, filled_volume=0.1,
            error_code=None, reported_at=T0,
        )
        recorded = engine.handle_execution_report(report)
        self.assertTrue(recorded)
        self.assertTrue(engine.command_resolved("corr-1"))


class TestCommandDelivered(unittest.TestCase):
    """command_delivered() -- mirrors command_resolved()'s own additive
    passthrough pattern. Lets Runtime's InFlightCommandRegistry tell "the
    EA actually polled and received this command" apart from "still
    sitting in CommandQueue, never yet delivered" -- the distinction the
    undelivered-command abandonment fix needs (see
    titan_protocol/runtime/in_flight_commands.py)."""

    def test_unknown_correlation_id_is_not_delivered(self):
        engine, _, _, _ = make_engine()
        self.assertFalse(engine.command_delivered("never-submitted"))

    def test_enqueued_but_not_yet_polled_is_not_delivered(self):
        engine, queue, _, _ = make_engine()
        queue.enqueue(make_command(correlation_id="corr-1"), is_ready=True)
        self.assertFalse(engine.command_delivered("corr-1"))

    def test_polled_command_is_delivered(self):
        engine, queue, _, _ = make_engine()
        queue.enqueue(make_command(correlation_id="corr-1"), is_ready=True)
        delivered = engine.poll_commands(T0)
        self.assertEqual(len(delivered), 1)
        self.assertTrue(engine.command_delivered("corr-1"))


class TestSubmitAndPollCommands(unittest.TestCase):
    def test_submit_rejected_when_not_ready(self):
        engine, _, _, metrics = make_engine()
        reason = engine.submit_command(make_command(correlation_id="c1"), T0)
        self.assertIsNotNone(reason)
        self.assertEqual(metrics.command_rejected_count, 1)

    def test_submit_succeeds_after_heartbeat_then_poll_delivers(self):
        engine, _, _, metrics = make_engine()
        engine.handle_heartbeat(
            HeartbeatMessage(schema_version=SCHEMA_VERSION, magic_number=20260709, account_login=1,
                              terminal_connected=True, received_at=T0)
        )
        reason = engine.submit_command(make_command(correlation_id="c1", issued_at=T0), T0)
        self.assertIsNone(reason)
        self.assertEqual(metrics.command_submitted_count, 1)
        delivered = engine.poll_commands(T0 + timedelta(seconds=1))
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].correlation_id, "c1")

    def test_submit_rejects_disallowed_symbol(self):
        engine, _, _, _ = make_engine()
        engine.handle_heartbeat(
            HeartbeatMessage(schema_version=SCHEMA_VERSION, magic_number=20260709, account_login=1,
                              terminal_connected=True, received_at=T0)
        )
        reason = engine.submit_command(make_command(correlation_id="c1", symbol="XAUUSD"), T0)
        self.assertEqual(reason.value, "SYMBOL_NOT_ALLOWED")

    def test_submit_rejects_excess_volume(self):
        config = make_config(max_lot_size=1.0)
        engine, _, _, _ = make_engine(config)
        engine.handle_heartbeat(
            HeartbeatMessage(schema_version=SCHEMA_VERSION, magic_number=20260709, account_login=1,
                              terminal_connected=True, received_at=T0)
        )
        reason = engine.submit_command(make_command(correlation_id="c1", volume=5.0), T0)
        self.assertEqual(reason.value, "VOLUME_EXCEEDS_MAX")

    def test_all_six_command_kinds_are_submittable(self):
        engine, _, _, _ = make_engine()
        engine.handle_heartbeat(
            HeartbeatMessage(schema_version=SCHEMA_VERSION, magic_number=20260709, account_login=1,
                              terminal_connected=True, received_at=T0)
        )
        for i, kind in enumerate(CommandKind):
            reason = engine.submit_command(make_command(correlation_id=f"c-{i}", command_kind=kind), T0)
            self.assertIsNone(reason, f"{kind} was rejected: {reason}")


class TestExecutionReport(unittest.TestCase):
    def test_execution_report_recorded_once(self):
        engine, queue, _, metrics = make_engine()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        report = ExecutionReport(
            schema_version=SCHEMA_VERSION, correlation_id="c1", magic_number=20260709,
            success=True, broker_ticket="t1", filled_price=1.1, filled_volume=0.1,
            error_code=None, reported_at=T0,
        )
        recorded = engine.handle_execution_report(report)
        self.assertTrue(recorded)
        self.assertEqual(metrics.execution_report_count, 1)

    def test_duplicate_execution_report_rejected_and_metered(self):
        engine, queue, _, metrics = make_engine()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        report = ExecutionReport(
            schema_version=SCHEMA_VERSION, correlation_id="c1", magic_number=20260709,
            success=True, broker_ticket="t1", filled_price=1.1, filled_volume=0.1,
            error_code=None, reported_at=T0,
        )
        engine.handle_execution_report(report)
        recorded_again = engine.handle_execution_report(report)
        self.assertFalse(recorded_again)
        self.assertEqual(metrics.duplicate_execution_report_count, 1)


class TestTradeTransactionDriftDetection(unittest.TestCase):
    def test_matches_known_execution_ticket(self):
        engine, queue, _, metrics = make_engine()
        queue.enqueue(make_command(correlation_id="c1"), is_ready=True)
        engine.handle_execution_report(
            ExecutionReport(
                schema_version=SCHEMA_VERSION, correlation_id="c1", magic_number=20260709,
                success=True, broker_ticket="t1", filled_price=1.1, filled_volume=0.1,
                error_code=None, reported_at=T0,
            )
        )
        report = TradeTransactionReport(
            schema_version=SCHEMA_VERSION, magic_number=20260709, symbol="EURUSD",
            deal_ticket="t1", order_ticket="t1", transaction_type="DEAL_ADD",
            volume=0.1, price=1.1, reported_at=T0,
        )
        matched = engine.handle_trade_transaction(report)
        self.assertTrue(matched)
        self.assertEqual(metrics.trade_transaction_drift_count, 0)

    def test_flags_drift_for_unknown_ticket(self):
        engine, _, _, metrics = make_engine()
        report = TradeTransactionReport(
            schema_version=SCHEMA_VERSION, magic_number=20260709, symbol="EURUSD",
            deal_ticket="mystery-ticket", order_ticket="mystery-ticket", transaction_type="DEAL_ADD",
            volume=0.1, price=1.1, reported_at=T0,
        )
        matched = engine.handle_trade_transaction(report)
        self.assertFalse(matched)
        self.assertEqual(metrics.trade_transaction_drift_count, 1)
        self.assertEqual(metrics.trade_transaction_count, 1)

    def test_none_ticket_is_never_flagged_as_drift(self):
        engine, _, _, metrics = make_engine()
        report = TradeTransactionReport(
            schema_version=SCHEMA_VERSION, magic_number=20260709, symbol=None,
            deal_ticket=None, order_ticket=None, transaction_type="ORDER_ADD",
            volume=None, price=None, reported_at=T0,
        )
        matched = engine.handle_trade_transaction(report)
        self.assertTrue(matched)
        self.assertEqual(metrics.trade_transaction_drift_count, 0)


class TestHandleError(unittest.TestCase):
    def test_error_report_stored(self):
        engine, _, _, metrics = make_engine()
        error = ErrorReport(
            schema_version=SCHEMA_VERSION, magic_number=20260709, error_code="WEBREQUEST_FAILED",
            message="webrequest failed", context="OnTimer", reported_at=T0,
        )
        engine.handle_error(error)
        self.assertEqual(len(engine.errors), 1)
        self.assertEqual(metrics.error_report_count, 1)


class TestEmergencyStop(unittest.TestCase):
    def test_activate_blocks_further_enqueue(self):
        engine, queue, _, metrics = make_engine()
        engine.activate_emergency_stop("operator_requested", T0)
        self.assertTrue(engine.emergency_stop_state.active)
        self.assertEqual(
            queue.enqueue(make_command(correlation_id="c1"), is_ready=True).value, "EMERGENCY_STOP_ACTIVE"
        )
        self.assertEqual(metrics.emergency_stop_count, 1)

    def test_deactivate_restores_normal_flow(self):
        engine, queue, _, _ = make_engine()
        engine.activate_emergency_stop("operator_requested", T0)
        engine.deactivate_emergency_stop()
        self.assertFalse(engine.emergency_stop_state.active)
        self.assertIsNone(queue.enqueue(make_command(correlation_id="c1"), is_ready=True))

    def test_deactivate_is_logged_same_as_activate(self):
        """Phase 1.5 hotfix: deactivate_emergency_stop() previously
        produced no log record at all, while activate_emergency_stop()
        did -- an administrative action with zero audit trail, found
        during Phase 1.5 observability validation."""
        logger = logging.getLogger("titan_protocol.bridge")
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        logger.addHandler(handler)
        try:
            engine, _, _, _ = make_engine()
            engine.activate_emergency_stop("operator_requested", T0)
            engine.deactivate_emergency_stop()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        stop_events = [r for r in records if r.msg == "bridge.emergency_stop"]
        self.assertEqual(len(stop_events), 2, "expected one log record for activate and one for deactivate")
        self.assertTrue(stop_events[0].active)
        self.assertFalse(stop_events[1].active)


if __name__ == "__main__":
    unittest.main()
