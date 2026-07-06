"""Phase 4 end-to-end integration tests — Paper Trading Runner, Session
Manager, Forward Testing Engine, Prop Firm Validator, Report Generator,
and Validation Dashboard, all exercised against a **real**
`PipelineOrchestrator` (Phase 2's own already-proven `build_orchestrator`/
`feed_healthy_bars` fixtures) — never a synthetic pipeline of this
package's own invention.

Covers the 6 scenarios explicitly required: full paper-trading lifecycle,
session transitions, prop-rule enforcement (reporting, never blocking),
recovery during paper trading, reporting, and dashboard updates.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import List

from phantom_pipeline.compliance_engine import ComplianceEngineMetrics
from phantom_pipeline.execution_validator import ExecutionValidatorMetrics
from phantom_pipeline.mt5_bridge import MT5BridgeMetrics
from phantom_pipeline.mt5_bridge.models import ConnectionStatus
from phantom_pipeline.orchestrator import ScanCycleResult
from phantom_pipeline.paper_trading.account_tracker import AccountTracker
from phantom_pipeline.paper_trading.forward_test_engine import ForwardTestEngine
from phantom_pipeline.paper_trading.paper_trading_runner import PaperTradingRunner
from phantom_pipeline.paper_trading.prop_firm_validator import FTMO_PROFILE, PropFirmValidator, RuleStatus
from phantom_pipeline.paper_trading.report_generator import ReportGenerator
from phantom_pipeline.paper_trading.session_manager import SessionManager
from phantom_pipeline.paper_trading.validation_dashboard import ValidationDashboardBuilder
from phantom_pipeline.watchdog import WatchdogMetrics
from phantom_pipeline.watchdog.models import HealthState, RecoveryActionType, RecoveryOutcome
from phantom_pipeline.watchdog.engine import WatchdogEngine
from phantom_pipeline.watchdog.real_recovery_executor import RealRecoveryActionExecutor
from phantom_pipeline.watchdog.state_store import InMemoryWatchdogStateStore

from tests.phantom_pipeline.orchestrator._fixtures import (
    PRIMARY_TIMEFRAME,
    SYMBOL,
    TIMEFRAME,
    build_orchestrator,
    feed_healthy_bars,
    make_broker_state,
    make_compliance_account_state,
    make_execution_account_state,
    make_news_state,
    make_risk_account_state,
)

STOP_DISTANCE = 0.0050
WEEKEND_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)  # Saturday


class _FakeMarketDataSource:
    """A test-only tick source conforming to `MarketDataSource`'s
    structural protocol — stands in for a live MT5 feed exactly like
    every other Phase 3/4 test's fake adapter, feeding
    `DataPipeline.process_raw_tick` (the real, public ingestion path),
    never bypassing it."""

    def __init__(self, symbol: str, start: datetime, start_price: float = 1.1050) -> None:
        self._symbol = symbol
        self._next_tick_at = start
        self._price = start_price
        self.connected = False
        self.poll_count = 0

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def poll_ticks(self, pipeline, symbol, **kwargs):
        self.poll_count += 1
        produced = pipeline.process_raw_tick(
            raw_symbol=symbol, raw_timestamp=self._next_tick_at,
            bid=self._price, ask=self._price + 0.0002, last=None, volume=1.0,
            source="test-live", market_status="OPEN",
        )
        self._next_tick_at += timedelta(minutes=1)
        return produced


def _build_runner(orchestrator, now, confirm_demo=lambda: True):
    market_data_source = _FakeMarketDataSource(SYMBOL, start=now)
    runner = PaperTradingRunner(
        orchestrator=orchestrator,
        mt5_adapter=orchestrator.mt5_bridge.adapter,
        market_data_adapter=market_data_source,
        session_manager=SessionManager(),
        account_tracker=AccountTracker(initial_equity=10000.0),
        confirm_demo_account=confirm_demo,
    )
    return runner, market_data_source


def _run_one_cycle(orchestrator, runner, now, compliance_approve=True):
    last_tick_at = feed_healthy_bars(orchestrator.data_pipeline, start=now - timedelta(minutes=121))
    orchestrator.mt5_bridge.connect(now)
    orchestrator.mt5_bridge.synchronize(now, expected_position_ids=())
    entry_price = orchestrator.data_pipeline.get_snapshot(SYMBOL).price

    result = runner.run_scan_cycle(
        SYMBOL, (TIMEFRAME,), PRIMARY_TIMEFRAME, now, now,
        risk_account_state=make_risk_account_state(),
        compliance_account_state=make_compliance_account_state(approve=compliance_approve),
        execution_account_state=make_execution_account_state(),
        broker_state=make_broker_state(),
        news_state=make_news_state(),
        stop_distance=STOP_DISTANCE,
        expected_slippage=0.0001,
        reference_price=entry_price,
        intended_stop_loss=entry_price - STOP_DISTANCE,
        intended_take_profit=entry_price + STOP_DISTANCE * 3,
    )
    return result


class TestFullPaperTradingLifecycle(unittest.TestCase):
    def test_connect_run_cycle_and_observe_account(self):
        orchestrator = build_orchestrator()
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)  # Monday
        runner, market_data_source = _build_runner(orchestrator, now)

        self.assertTrue(runner.connect())
        result = _run_one_cycle(orchestrator, runner, now)

        self.assertIsInstance(result, ScanCycleResult)
        self.assertGreater(len(result.candidate_results), 0)
        self.assertEqual(market_data_source.poll_count, 1)  # live tick pulled exactly once

        snapshot = runner.observe_account(now)
        self.assertEqual(snapshot.equity, 10000.0)
        self.assertEqual(snapshot.daily_drawdown_pct, 0.0)

    def test_never_places_a_live_trade_when_not_demo(self):
        orchestrator = build_orchestrator()
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
        runner, _ = _build_runner(orchestrator, now, confirm_demo=lambda: False)
        with self.assertRaises(RuntimeError):
            runner.connect()
        with self.assertRaises(RuntimeError):
            runner.run_scan_cycle(SYMBOL, (TIMEFRAME,), PRIMARY_TIMEFRAME, now, now)


class TestSessionTransitions(unittest.TestCase):
    def test_weekend_cycle_never_touches_the_real_pipeline(self):
        orchestrator = build_orchestrator()
        runner, market_data_source = _build_runner(orchestrator, WEEKEND_NOW)
        runner.connect()
        ticks_before = orchestrator.data_pipeline.ticks_processed

        result = runner.run_scan_cycle(SYMBOL, (TIMEFRAME,), PRIMARY_TIMEFRAME, WEEKEND_NOW, WEEKEND_NOW)

        self.assertIsNone(result)
        self.assertEqual(market_data_source.poll_count, 0)
        self.assertEqual(orchestrator.data_pipeline.ticks_processed, ticks_before)

    def test_weekday_cycle_proceeds_normally(self):
        orchestrator = build_orchestrator()
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
        runner, _ = _build_runner(orchestrator, now)
        runner.connect()
        result = _run_one_cycle(orchestrator, runner, now)
        self.assertIsInstance(result, ScanCycleResult)


class TestPropRuleEnforcementIsAdvisoryOnly(unittest.TestCase):
    def test_prop_firm_status_never_mutates_real_decisions(self):
        orchestrator = build_orchestrator()
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
        runner, _ = _build_runner(orchestrator, now)
        runner.connect()
        result = _run_one_cycle(orchestrator, runner, now)

        risk_decisions = [cr.risk_decision for cr in result.candidate_results if cr.risk_decision is not None]
        compliance_decisions = [cr.compliance_decision for cr in result.candidate_results if cr.compliance_decision is not None]
        original_verdicts = [d.verdict for d in compliance_decisions]

        validator = PropFirmValidator(FTMO_PROFILE)
        status = validator.build_status(
            risk_config=orchestrator.risk_engine.config,
            compliance_config=orchestrator.compliance_engine.config,
            account_snapshot=runner.observe_account(now),
            risk_decisions=risk_decisions,
            open_position_count=0,
            compliance_decisions=compliance_decisions,
            now=now,
        )

        self.assertIsInstance(status.overall_status, RuleStatus)
        # Advisory only: the real decision objects are completely unchanged.
        self.assertEqual([d.verdict for d in compliance_decisions], original_verdicts)
        for decision in compliance_decisions:
            self.assertIn(decision, [cr.compliance_decision for cr in result.candidate_results])


class TestRecoveryDuringPaperTrading(unittest.TestCase):
    def test_real_recovery_executor_attempt_reflected_in_forward_test_report(self):
        command_runner_calls = []

        def fake_command_runner(command, timeout_seconds):
            command_runner_calls.append(command)
            return True

        recovery_executor = RealRecoveryActionExecutor(
            service_units={"mt5_bridge": "phantom-mt5-bridge.service"},
            command_runner=fake_command_runner,
        )
        watchdog_metrics = WatchdogMetrics()
        watchdog_engine = WatchdogEngine(InMemoryWatchdogStateStore(), recovery_executor, metrics=watchdog_metrics)
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)

        status, alert = watchdog_engine.attempt_recovery(
            "mt5_bridge", RecoveryActionType.RESTART_SERVICE, HealthState.DEGRADED, now
        )

        self.assertEqual(status.last_outcome, RecoveryOutcome.SUCCEEDED)
        self.assertEqual(len(command_runner_calls), 1)

        orchestrator = build_orchestrator()
        forward_test_engine = ForwardTestEngine(
            analytics=orchestrator.analytics,
            execution_validator_metrics=ExecutionValidatorMetrics(),
            mt5_bridge_metrics=MT5BridgeMetrics(),
            watchdog_metrics=watchdog_metrics,
        )
        report = forward_test_engine.build_report([], None, now, now, now)
        self.assertEqual(report.recovery_attempt_count, 1)
        self.assertEqual(report.recovery_success_rate, 1.0)


class TestReportingAndDashboardUpdates(unittest.TestCase):
    def test_daily_report_and_dashboard_reflect_a_real_cycle(self):
        orchestrator = build_orchestrator()
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
        runner, _ = _build_runner(orchestrator, now)
        runner.connect()
        result = _run_one_cycle(orchestrator, runner, now)

        records = [
            orchestrator.analytics.build_provenance_record(cr.candidate.trace_id, now)
            for cr in result.candidate_results
            if cr.candidate is not None
        ]
        records = [r for r in records if r is not None]
        self.assertGreater(len(records), 0)

        forward_test_engine = ForwardTestEngine(
            analytics=orchestrator.analytics,
            execution_validator_metrics=ExecutionValidatorMetrics(),
            mt5_bridge_metrics=MT5BridgeMetrics(),
            watchdog_metrics=WatchdogMetrics(),
        )
        report_generator = ReportGenerator(
            analytics=orchestrator.analytics,
            forward_test_engine=forward_test_engine,
            compliance_engine_metrics=ComplianceEngineMetrics(),
            execution_validator_metrics=ExecutionValidatorMetrics(),
        )
        snapshot = runner.observe_account(now)
        daily_report = report_generator.generate_daily(records, now, account_snapshot=snapshot)

        self.assertEqual(daily_report.period_kind, "DAILY")
        self.assertIsNotNone(daily_report.forward_test_report)

        system_health = runner.evaluate_watchdog_health(now)
        mt5_connection = ConnectionStatus(
            schema_version=1, state=orchestrator.mt5_bridge.state, detail="from cycle", timestamp=now,
        )
        dashboard_builder = ValidationDashboardBuilder(SessionManager())
        dashboard_snapshot = dashboard_builder.build(
            now, system_health, mt5_connection, records,
            forward_test_engine.build_report(records, snapshot, now, now, now),
        )

        self.assertIs(dashboard_snapshot.system_health, system_health)
        self.assertEqual(dashboard_snapshot.mt5_connection.state, orchestrator.mt5_bridge.state)
        self.assertEqual(len(dashboard_snapshot.todays_trades), len(records))


if __name__ == "__main__":
    unittest.main()
