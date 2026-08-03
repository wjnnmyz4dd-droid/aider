"""ValidationDashboardBuilder tests — verifies pure read-only aggregation:
every field is either an already-produced object passed through verbatim,
or a plain filter over already-collected records using SessionManager's
own trading-day boundary."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.analytics.models import FinalOutcome, OutcomeKind, TradeProvenanceRecord
from phantom_pipeline.mt5_bridge.models import ConnectionState, ConnectionStatus
from phantom_pipeline.paper_trading.forward_test_engine import ForwardTestReport
from phantom_pipeline.paper_trading.session_manager import SessionManager
from phantom_pipeline.paper_trading.validation_dashboard import ValidationDashboardBuilder
from phantom_pipeline.watchdog.models import HealthState, SystemHealth

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


def _record(trace_id: str, collected_at: datetime, outcome_kind: OutcomeKind) -> TradeProvenanceRecord:
    final_outcome = FinalOutcome(
        outcome_kind=outcome_kind, realized_pnl=10.0 if outcome_kind == OutcomeKind.CLOSED else None,
        mae=None, mfe=None, close_reason=None, rejected_at_stage=None, rejection_reason=None,
    )
    return TradeProvenanceRecord(
        schema_version=1, trace_id=trace_id, scanner_observation=None, candidate=None, score_result=None,
        risk_decision=None, compliance_decision=None, execution_decision=None, broker_events=(),
        fill_reports=(), position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=final_outcome, analytics_version="1.0.0-phase1", collected_at=collected_at,
    )


def _system_health() -> SystemHealth:
    return SystemHealth(
        schema_version=1, trace_id="health-1", overall_health=HealthState.HEALTHY,
        component_health=(), heartbeat_statuses=(), recovery_statuses=(), timestamp=T0,
        system_version="1.0.0-phase1",
    )


def _connection_status() -> ConnectionStatus:
    return ConnectionStatus(schema_version=1, state=ConnectionState.READY, detail="ready", timestamp=T0)


def _performance() -> ForwardTestReport:
    return ForwardTestReport(
        schema_version=1, generated_at=T0, window_start=T0, window_end=T0, trade_count=0,
        win_rate=None, profit_factor=None, expectancy=None, average_rr=None, max_drawdown=None,
        daily_drawdown_pct=None, total_drawdown_pct=None, average_validation_latency_seconds=0.0,
        average_broker_latency_seconds=0.0, average_fill_latency_seconds=0.0, average_slippage=None,
        slippage_sample_size=0, missed_trade_count=0, blocked_trade_count=0, duplicate_prevention_count=0,
        recovery_attempt_count=0, recovery_success_rate=0.0, average_recovery_time_seconds=0.0,
        analytics_version="1.0.0-phase1",
    )


class TestPassthroughFields(unittest.TestCase):
    def test_system_health_passed_through_verbatim(self):
        builder = ValidationDashboardBuilder()
        health = _system_health()
        snapshot = builder.build(T0, health, _connection_status(), [], _performance())
        self.assertIs(snapshot.system_health, health)

    def test_mt5_connection_passed_through_verbatim(self):
        builder = ValidationDashboardBuilder()
        conn = _connection_status()
        snapshot = builder.build(T0, _system_health(), conn, [], _performance())
        self.assertIs(snapshot.mt5_connection, conn)

    def test_performance_passed_through_verbatim(self):
        builder = ValidationDashboardBuilder()
        perf = _performance()
        snapshot = builder.build(T0, _system_health(), _connection_status(), [], perf)
        self.assertIs(snapshot.performance, perf)

    def test_prop_firm_status_none_when_not_supplied(self):
        builder = ValidationDashboardBuilder()
        snapshot = builder.build(T0, _system_health(), _connection_status(), [], _performance())
        self.assertIsNone(snapshot.prop_firm_status)


class TestTradeFiltering(unittest.TestCase):
    def test_todays_trades_excludes_previous_day(self):
        builder = ValidationDashboardBuilder(SessionManager())
        yesterday_record = _record("t1", T0 - timedelta(days=1), OutcomeKind.CLOSED)
        today_record = _record("t2", T0, OutcomeKind.CLOSED)
        snapshot = builder.build(T0, _system_health(), _connection_status(), [yesterday_record, today_record], _performance())
        trace_ids = [r.trace_id for r in snapshot.todays_trades]
        self.assertEqual(trace_ids, ["t2"])

    def test_open_and_closed_positions_partitioned_correctly(self):
        builder = ValidationDashboardBuilder(SessionManager())
        open_record = _record("open-1", T0, OutcomeKind.OPEN)
        closed_record = _record("closed-1", T0, OutcomeKind.CLOSED)
        rejected_record = _record("rejected-1", T0, OutcomeKind.REJECTED)
        snapshot = builder.build(
            T0, _system_health(), _connection_status(),
            [open_record, closed_record, rejected_record], _performance(),
        )
        self.assertEqual([r.trace_id for r in snapshot.open_positions], ["open-1"])
        self.assertEqual([r.trace_id for r in snapshot.closed_positions], ["closed-1"])
        # rejected trades appear in today's trades but neither position bucket
        self.assertEqual(len(snapshot.todays_trades), 3)


if __name__ == "__main__":
    unittest.main()
