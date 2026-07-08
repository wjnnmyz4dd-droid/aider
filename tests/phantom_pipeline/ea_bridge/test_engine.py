"""`EABridgeEngine` tests — telemetry forwarding, command relay, and
emergency-stop control (`ADR-023` §2)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom_pipeline.ea_bridge.broker_adapter import EABrokerAdapter
from phantom_pipeline.ea_bridge.command_queue import CommandQueue
from phantom_pipeline.ea_bridge.engine import EABridgeEngine
from phantom_pipeline.ea_bridge.metrics import EABridgeMetrics
from phantom_pipeline.ea_bridge.models import (
    BarMessage,
    EAAccountState,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PositionReport,
    SCHEMA_VERSION,
    TickMessage,
)
from phantom_pipeline.scanner.models import Direction
from tests.phantom_pipeline.ea_bridge._fixtures import T0, make_command, make_config, make_data_pipeline


def make_engine(config=None):
    config = config or make_config()
    queue = CommandQueue(config)
    adapter = EABrokerAdapter(queue, clock=lambda: T0, config=config)
    metrics = EABridgeMetrics()
    engine = EABridgeEngine(config, make_data_pipeline(), queue, adapter, metrics=metrics)
    return engine, queue, metrics


class TestHandleHeartbeat(unittest.TestCase):
    def test_records_heartbeat_and_increments_metric(self):
        engine, _, metrics = make_engine()
        message = HeartbeatMessage(
            schema_version=SCHEMA_VERSION, magic_number=20260708, terminal_time=T0,
            account_login=1, connected=True, received_at=T0,
        )
        engine.handle_heartbeat(message)
        self.assertEqual(metrics.heartbeat_count, 1)


class TestHandleAccountState(unittest.TestCase):
    def test_stores_latest_account_state(self):
        engine, _, metrics = make_engine()
        state = EAAccountState(
            schema_version=SCHEMA_VERSION, magic_number=20260708, equity=10500.0, balance=10000.0,
            margin=100.0, free_margin=10400.0, currency="USD", received_at=T0,
        )
        engine.handle_account_state(state)
        self.assertEqual(engine.latest_account_state.equity, 10500.0)
        self.assertEqual(metrics.account_update_count, 1)


class TestHandleTick(unittest.TestCase):
    def test_forwards_to_data_pipeline_without_error(self):
        engine, _, metrics = make_engine()
        tick = TickMessage(
            schema_version=SCHEMA_VERSION, symbol="EURUSD", bid=1.1000, ask=1.1002, last=None,
            volume=1.0, terminal_time=T0, received_at=T0,
        )
        bars = engine.handle_tick(tick)
        self.assertIsInstance(bars, list)
        self.assertEqual(metrics.tick_count, 1)


class TestHandleBars(unittest.TestCase):
    def test_forwards_bars_to_data_pipeline(self):
        engine, _, metrics = make_engine()
        bars = (
            BarMessage(
                schema_version=SCHEMA_VERSION, symbol="EURUSD", timeframe="M15",
                open=1.10, high=1.11, low=1.09, close=1.105, volume=100.0,
                bar_time=T0, received_at=T0,
            ),
        )
        engine.handle_bars(bars)
        self.assertEqual(metrics.bar_count, 1)


class TestHandlePositions(unittest.TestCase):
    def test_stores_and_reflects_into_broker_adapter(self):
        engine, _, metrics = make_engine()
        adapter = engine._broker_adapter
        positions = (
            PositionReport(
                schema_version=SCHEMA_VERSION, position_id="p1", symbol="EURUSD",
                direction=Direction.UP, volume=0.1, open_price=1.10, stop_loss=1.09,
                take_profit=1.12, unrealized_pnl=5.0, magic_number=20260708, received_at=T0,
            ),
        )
        engine.handle_positions(positions)
        self.assertEqual(engine.latest_positions[0].position_id, "p1")
        self.assertEqual(adapter.query_open_position_ids(), ("p1",))
        self.assertEqual(metrics.position_update_count, 1)


class TestPollAndExecutionReport(unittest.TestCase):
    def test_poll_commands_returns_enqueued_command(self):
        engine, queue, _ = make_engine()
        queue.enqueue(make_command(execution_id="exec-1", issued_at=T0), is_ready=True)
        commands = engine.poll_commands(T0 + timedelta(seconds=1))
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].execution_id, "exec-1")

    def test_execution_report_recorded_once(self):
        engine, queue, metrics = make_engine()
        queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        report = ExecutionReport(
            schema_version=SCHEMA_VERSION, execution_id="exec-1", magic_number=20260708,
            success=True, broker_ticket="t1", filled_price=1.1, filled_size=0.1,
            reason=None, reported_at=T0,
        )
        recorded = engine.handle_execution_report(report)
        self.assertTrue(recorded)
        self.assertEqual(metrics.execution_report_count, 1)

    def test_duplicate_execution_report_rejected_and_metered(self):
        engine, queue, metrics = make_engine()
        queue.enqueue(make_command(execution_id="exec-1"), is_ready=True)
        report = ExecutionReport(
            schema_version=SCHEMA_VERSION, execution_id="exec-1", magic_number=20260708,
            success=True, broker_ticket="t1", filled_price=1.1, filled_size=0.1,
            reason=None, reported_at=T0,
        )
        engine.handle_execution_report(report)
        recorded_again = engine.handle_execution_report(report)
        self.assertFalse(recorded_again)
        self.assertEqual(metrics.duplicate_execution_report_count, 1)


class TestHandleError(unittest.TestCase):
    def test_error_report_stored(self):
        engine, _, metrics = make_engine()
        error = ErrorReport(
            schema_version=SCHEMA_VERSION, magic_number=20260708, code=1001,
            message="webrequest failed", context="OnTimer", reported_at=T0,
        )
        engine.handle_error(error)
        self.assertEqual(len(engine.errors), 1)
        self.assertEqual(metrics.error_report_count, 1)


class TestEmergencyStop(unittest.TestCase):
    def test_activate_blocks_further_enqueue(self):
        engine, queue, metrics = make_engine()
        engine.activate_emergency_stop("operator_requested", T0)
        self.assertTrue(engine.emergency_stop_state.active)
        self.assertEqual(queue.enqueue(make_command(execution_id="exec-1"), is_ready=True), "emergency_stop_active")
        self.assertEqual(metrics.emergency_stop_count, 1)

    def test_deactivate_restores_normal_flow(self):
        engine, queue, _ = make_engine()
        engine.activate_emergency_stop("operator_requested", T0)
        engine.deactivate_emergency_stop()
        self.assertFalse(engine.emergency_stop_state.active)
        self.assertIsNone(queue.enqueue(make_command(execution_id="exec-1"), is_ready=True))


if __name__ == "__main__":
    unittest.main()
