"""ForwardTestEngine tests — verifies this is a pure attribution layer:
every number traces back to an already-computed object (`PerformanceStatistics`,
a stage's own `*Metrics`) or a transparent aggregation over already-recorded
`TradeProvenanceRecord` fields, never a second independent computation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Optional

from phantom_pipeline.analytics import AnalyticsEngine, InMemoryTradeProvenanceStore
from phantom_pipeline.analytics.models import FinalOutcome, OutcomeKind, TradeProvenanceRecord
from phantom_pipeline.data_pipeline.models import MarketSnapshot
from phantom_pipeline.data_pipeline.models import SCHEMA_VERSION as PIPELINE_SCHEMA_VERSION
from phantom_pipeline.execution_validator import ExecutionValidatorMetrics
from phantom_pipeline.mt5_bridge import MT5BridgeMetrics
from phantom_pipeline.mt5_bridge.models import FillReport
from phantom_pipeline.paper_trading.account_tracker import AccountSnapshot
from phantom_pipeline.paper_trading.forward_test_engine import ForwardTestEngine
from phantom_pipeline.risk_engine.models import RiskDecision, RiskTier
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.watchdog import WatchdogMetrics
from phantom_pipeline.watchdog.models import HealthState, RecoveryOutcome

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


def _risk_decision(approved_risk_amount: float = 100.0) -> RiskDecision:
    return RiskDecision(
        schema_version=1, trace_id="t1", candidate_id="c1", strategy_id="s1",
        symbol="EURUSD", timeframe="M1", timestamp=T0, direction=Direction.UP,
        approved_risk_percent=1.0, approved_risk_amount=approved_risk_amount,
        lot_size=0.5, risk_tier=RiskTier.NORMAL, limiting_constraint="none",
        constraint_evaluations=(), reason_codes=(), risk_engine_version="1.0.0-phase1",
    )


def _record(
    trace_id: str,
    realized_pnl: Optional[float] = None,
    outcome_kind: OutcomeKind = OutcomeKind.CLOSED,
    rejected_at_stage: Optional[str] = None,
    risk_decision: Optional[RiskDecision] = None,
    fill_price: Optional[float] = None,
    snapshot_price: Optional[float] = None,
) -> TradeProvenanceRecord:
    final_outcome = FinalOutcome(
        outcome_kind=outcome_kind, realized_pnl=realized_pnl, mae=None, mfe=None,
        close_reason="take_profit" if realized_pnl is not None else None,
        rejected_at_stage=rejected_at_stage, rejection_reason=None,
    ) if (realized_pnl is not None or rejected_at_stage is not None) else None

    fill_reports = ()
    if fill_price is not None:
        fill_reports = (FillReport(
            schema_version=1, execution_id="exec-1", trace_id=trace_id,
            fill_price=fill_price, fill_size=0.5, fill_timestamp=T0,
        ),)
    market_snapshots = ()
    if snapshot_price is not None:
        market_snapshots = (MarketSnapshot(
            schema_version=PIPELINE_SCHEMA_VERSION, trace_id=trace_id, symbol="EURUSD",
            timestamp=T0, price=snapshot_price, spread=0.0002, market_status="OPEN",
        ),)

    return TradeProvenanceRecord(
        schema_version=1, trace_id=trace_id, scanner_observation=None, candidate=None,
        score_result=None, risk_decision=risk_decision, compliance_decision=None,
        execution_decision=None, broker_events=(), fill_reports=fill_reports,
        position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=market_snapshots,
        final_outcome=final_outcome, analytics_version="1.0.0-phase1", collected_at=T0,
    )


def _engine() -> ForwardTestEngine:
    analytics = AnalyticsEngine(store=InMemoryTradeProvenanceStore())
    return ForwardTestEngine(
        analytics=analytics,
        execution_validator_metrics=ExecutionValidatorMetrics(),
        mt5_bridge_metrics=MT5BridgeMetrics(),
        watchdog_metrics=WatchdogMetrics(),
    )


class TestForwardTestEngineAttribution(unittest.TestCase):
    def test_win_rate_and_profit_factor_come_from_analytics(self):
        records = [
            _record("t1", realized_pnl=100.0, risk_decision=_risk_decision(100.0)),
            _record("t2", realized_pnl=-50.0, risk_decision=_risk_decision(100.0)),
        ]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertEqual(report.trade_count, 2)
        self.assertEqual(report.win_rate, 0.5)
        self.assertAlmostEqual(report.profit_factor, 2.0)

    def test_average_rr_computed_from_realized_pnl_over_risk_amount(self):
        records = [
            _record("t1", realized_pnl=200.0, risk_decision=_risk_decision(100.0)),
            _record("t2", realized_pnl=-100.0, risk_decision=_risk_decision(100.0)),
        ]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertAlmostEqual(report.average_rr, 0.5)  # (2.0 + -1.0) / 2

    def test_average_rr_none_when_no_risk_decision_present(self):
        records = [_record("t1", realized_pnl=100.0)]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertIsNone(report.average_rr)

    def test_missed_trade_counted_from_execution_validator_rejection(self):
        records = [_record("t1", rejected_at_stage="execution_validator")]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertEqual(report.missed_trade_count, 1)
        self.assertEqual(report.blocked_trade_count, 0)

    def test_blocked_trade_counted_from_compliance_rejection(self):
        records = [_record("t1", rejected_at_stage="compliance_engine")]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertEqual(report.blocked_trade_count, 1)
        self.assertEqual(report.missed_trade_count, 0)

    def test_slippage_computed_when_both_fill_and_snapshot_present(self):
        records = [_record("t1", realized_pnl=10.0, fill_price=1.1005, snapshot_price=1.1000)]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertAlmostEqual(report.average_slippage, 0.0005)
        self.assertEqual(report.slippage_sample_size, 1)

    def test_slippage_none_when_data_missing(self):
        records = [_record("t1", realized_pnl=10.0)]
        report = _engine().build_report(records, None, T0, T0, T0)
        self.assertIsNone(report.average_slippage)
        self.assertEqual(report.slippage_sample_size, 0)

    def test_account_snapshot_drawdown_passed_through_verbatim(self):
        snapshot = AccountSnapshot(
            schema_version=1, equity=9800.0, day_start_equity=10000.0, initial_equity=10000.0,
            peak_equity=10000.0, daily_drawdown_pct=2.0, total_drawdown_pct=2.0,
            total_drawdown_pct_from_peak=2.0, timestamp=T0,
        )
        report = _engine().build_report([], snapshot, T0, T0, T0)
        self.assertEqual(report.daily_drawdown_pct, 2.0)
        self.assertEqual(report.total_drawdown_pct, 2.0)

    def test_account_snapshot_none_when_not_supplied(self):
        report = _engine().build_report([], None, T0, T0, T0)
        self.assertIsNone(report.daily_drawdown_pct)
        self.assertIsNone(report.total_drawdown_pct)

    def test_duplicate_prevention_count_attributed_from_execution_validator_metrics(self):
        ev_metrics = ExecutionValidatorMetrics()
        from phantom_pipeline.execution_validator.models import ExecutionDecision, Verdict, CheckEvaluation, CheckStatus

        decision = ExecutionDecision(
            schema_version=1, trace_id="t1", candidate_id="c1", strategy_id="s1", symbol="EURUSD",
            timeframe="M1", timestamp=T0, direction=Direction.UP, verdict=Verdict.REJECT,
            blocking_reasons=("NO_DUPLICATE_REQUEST",),
            check_evaluations=(CheckEvaluation("NO_DUPLICATE_REQUEST", CheckStatus.FAILED, "duplicate"),),
            reason_codes=("NO_DUPLICATE_REQUEST",), warnings=(),
            execution_validator_version="1.0.0-phase1",
        )
        ev_metrics.record_decision(decision)
        analytics = AnalyticsEngine(store=InMemoryTradeProvenanceStore())
        engine = ForwardTestEngine(
            analytics=analytics, execution_validator_metrics=ev_metrics,
            mt5_bridge_metrics=MT5BridgeMetrics(), watchdog_metrics=WatchdogMetrics(),
        )
        report = engine.build_report([], None, T0, T0, T0)
        self.assertEqual(report.duplicate_prevention_count, 1)

    def test_recovery_stats_attributed_from_watchdog_metrics(self):
        wd_metrics = WatchdogMetrics()
        wd_metrics.record_recovery_attempt("mt5_bridge", RecoveryOutcome.SUCCEEDED, duration_seconds=1.5)
        analytics = AnalyticsEngine(store=InMemoryTradeProvenanceStore())
        engine = ForwardTestEngine(
            analytics=analytics, execution_validator_metrics=ExecutionValidatorMetrics(),
            mt5_bridge_metrics=MT5BridgeMetrics(), watchdog_metrics=wd_metrics,
        )
        report = engine.build_report([], None, T0, T0, T0)
        self.assertEqual(report.recovery_attempt_count, 1)
        self.assertEqual(report.recovery_success_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
