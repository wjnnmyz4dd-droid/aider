"""ReportGenerator tests — verifies best/worst pair/session/regime reuse
`AnalyticsEngine`'s own existing grouping methods, and that recovery
statistics are read from `ForwardTestReport`, never recomputed."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Optional

from phantom_pipeline.analytics import AnalyticsEngine, InMemoryTradeProvenanceStore
from phantom_pipeline.analytics.models import FinalOutcome, OutcomeKind, TradeProvenanceRecord
from phantom_pipeline.compliance_engine import ComplianceEngineMetrics
from phantom_pipeline.compliance_engine.models import CheckEvaluation, CheckStatus, ComplianceDecision
from phantom_pipeline.compliance_engine.models import Verdict as ComplianceVerdict
from phantom_pipeline.execution_validator import ExecutionValidatorMetrics
from phantom_pipeline.mt5_bridge import MT5BridgeMetrics
from phantom_pipeline.paper_trading.forward_test_engine import ForwardTestEngine
from phantom_pipeline.paper_trading.report_generator import ReportGenerator
from phantom_pipeline.risk_engine.models import RiskDecision, RiskTier
from phantom_pipeline.scanner.models import (
    DataQualityFlag,
    Direction,
    MarketPhase,
    RangeStructure,
    ScannerObservation,
    SessionState,
    StructureConfidence,
    StructureTrendState,
    SwingSequenceType,
    VolatilityLabel,
    VolatilityState,
)
from phantom_pipeline.watchdog import WatchdogMetrics

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)


def _scanner_observation(symbol: str, session_names, regime: RangeStructure) -> ScannerObservation:
    return ScannerObservation(
        schema_version=1, trace_id=f"trace-{symbol}", symbol=symbol, timestamp=T0,
        trend={}, structure=(), volatility=VolatilityState(label=VolatilityLabel.NORMAL, ratio=None),
        session=SessionState(active_sessions=tuple(session_names), window_position=None),
        liquidity_events=(), data_quality_flag=DataQualityFlag.NOMINAL,
        external_structure=StructureTrendState(direction=Direction.UP, sequence=SwingSequenceType.MIXED),
        internal_structure=StructureTrendState(direction=Direction.UP, sequence=SwingSequenceType.MIXED),
        swing_hierarchy=(), equal_highs=(), equal_lows=(),
        range_structure=regime, phase=MarketPhase.UNDEFINED,
        trend_acceleration=None, trend_exhaustion=None,
        structure_confidence=StructureConfidence.CLEAR,
    )


def _risk_decision_for(symbol: str) -> RiskDecision:
    return RiskDecision(
        schema_version=1, trace_id=f"trace-{symbol}", candidate_id="c1", strategy_id="s1",
        symbol=symbol, timeframe="M1", timestamp=T0, direction=Direction.UP,
        approved_risk_percent=1.0, approved_risk_amount=100.0, lot_size=0.5,
        risk_tier=RiskTier.NORMAL, limiting_constraint="none", constraint_evaluations=(),
        reason_codes=(), risk_engine_version="1.0.0-phase1",
    )


def _record(trace_id: str, symbol: str, session_names, regime: RangeStructure, realized_pnl: float) -> TradeProvenanceRecord:
    return TradeProvenanceRecord(
        schema_version=1, trace_id=trace_id,
        scanner_observation=_scanner_observation(symbol, session_names, regime),
        candidate=None, score_result=None, risk_decision=_risk_decision_for(symbol), compliance_decision=None,
        execution_decision=None, broker_events=(), fill_reports=(), position_management_decisions=(),
        position_updates=(), position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=FinalOutcome(
            outcome_kind=OutcomeKind.CLOSED, realized_pnl=realized_pnl, mae=None, mfe=None,
            close_reason="take_profit", rejected_at_stage=None, rejection_reason=None,
        ),
        analytics_version="1.0.0-phase1", collected_at=T0,
    )


def _generator():
    analytics = AnalyticsEngine(store=InMemoryTradeProvenanceStore())
    forward_test_engine = ForwardTestEngine(
        analytics=analytics, execution_validator_metrics=ExecutionValidatorMetrics(),
        mt5_bridge_metrics=MT5BridgeMetrics(), watchdog_metrics=WatchdogMetrics(),
    )
    return ReportGenerator(
        analytics=analytics, forward_test_engine=forward_test_engine,
        compliance_engine_metrics=ComplianceEngineMetrics(), execution_validator_metrics=ExecutionValidatorMetrics(),
    )


class TestBestWorstGrouping(unittest.TestCase):
    def test_best_and_worst_pair_reuse_analytics_grouping(self):
        records = [
            _record("t1", "EURUSD", ["LONDON"], RangeStructure.EXPANSION, 100.0),
            _record("t2", "GBPUSD", ["LONDON"], RangeStructure.EXPANSION, -50.0),
        ]
        report = _generator().generate("DAILY", records, T0, T0, T0)
        self.assertEqual(report.best_pair, "EURUSD")
        self.assertEqual(report.worst_pair, "GBPUSD")

    def test_best_and_worst_session(self):
        records = [
            _record("t1", "EURUSD", ["LONDON"], RangeStructure.EXPANSION, 200.0),
            _record("t2", "EURUSD", ["NEW_YORK"], RangeStructure.EXPANSION, -75.0),
        ]
        report = _generator().generate("DAILY", records, T0, T0, T0)
        self.assertEqual(report.best_session, "LONDON")
        self.assertEqual(report.worst_session, "NEW_YORK")

    def test_best_and_worst_regime(self):
        records = [
            _record("t1", "EURUSD", ["LONDON"], RangeStructure.EXPANSION, 150.0),
            _record("t2", "EURUSD", ["LONDON"], RangeStructure.COMPRESSION, -25.0),
        ]
        report = _generator().generate("DAILY", records, T0, T0, T0)
        self.assertEqual(report.best_regime, "EXPANSION")
        self.assertEqual(report.worst_regime, "COMPRESSION")

    def test_none_when_no_closed_records(self):
        report = _generator().generate("DAILY", [], T0, T0, T0)
        self.assertIsNone(report.best_pair)
        self.assertIsNone(report.worst_pair)


class TestBiggestWinnerLoser(unittest.TestCase):
    def test_biggest_winner_and_loser_identified(self):
        records = [
            _record("t1", "EURUSD", ["LONDON"], RangeStructure.EXPANSION, 500.0),
            _record("t2", "EURUSD", ["LONDON"], RangeStructure.EXPANSION, -300.0),
            _record("t3", "EURUSD", ["LONDON"], RangeStructure.EXPANSION, 50.0),
        ]
        report = _generator().generate("DAILY", records, T0, T0, T0)
        self.assertEqual(report.biggest_winner_trace_id, "t1")
        self.assertEqual(report.biggest_winner_pnl, 500.0)
        self.assertEqual(report.biggest_loser_trace_id, "t2")
        self.assertEqual(report.biggest_loser_pnl, -300.0)


class TestComplianceAndRecoveryAttribution(unittest.TestCase):
    def test_rule_blocking_frequency_attributed_from_compliance_metrics(self):
        compliance_metrics = ComplianceEngineMetrics()
        decision = ComplianceDecision(
            schema_version=1, trace_id="t1", candidate_id="c1", strategy_id="s1", symbol="EURUSD",
            timeframe="M1", timestamp=T0, direction=Direction.UP, verdict=ComplianceVerdict.BLOCK,
            blocking_rules=("DAILY_DRAWDOWN",), reason_codes=("DAILY_DRAWDOWN",),
            check_evaluations=(CheckEvaluation("DAILY_DRAWDOWN", CheckStatus.FAILED, "breach"),),
            compliance_engine_version="1.0.0-phase1",
        )
        compliance_metrics.record_decision(decision)
        analytics = AnalyticsEngine(store=InMemoryTradeProvenanceStore())
        forward_test_engine = ForwardTestEngine(
            analytics=analytics, execution_validator_metrics=ExecutionValidatorMetrics(),
            mt5_bridge_metrics=MT5BridgeMetrics(), watchdog_metrics=WatchdogMetrics(),
        )
        generator = ReportGenerator(
            analytics=analytics, forward_test_engine=forward_test_engine,
            compliance_engine_metrics=compliance_metrics, execution_validator_metrics=ExecutionValidatorMetrics(),
        )
        report = generator.generate("DAILY", [], T0, T0, T0)
        self.assertEqual(report.compliance_blocks_by_check["DAILY_DRAWDOWN"], 1)
        self.assertEqual(report.compliance_decisions_by_verdict["BLOCK"], 1)

    def test_recovery_statistics_come_from_forward_test_report_not_recomputed(self):
        wd_metrics = WatchdogMetrics()
        from phantom_pipeline.watchdog.models import RecoveryOutcome

        wd_metrics.record_recovery_attempt("mt5_bridge", RecoveryOutcome.SUCCEEDED, duration_seconds=2.0)
        analytics = AnalyticsEngine(store=InMemoryTradeProvenanceStore())
        forward_test_engine = ForwardTestEngine(
            analytics=analytics, execution_validator_metrics=ExecutionValidatorMetrics(),
            mt5_bridge_metrics=MT5BridgeMetrics(), watchdog_metrics=wd_metrics,
        )
        generator = ReportGenerator(
            analytics=analytics, forward_test_engine=forward_test_engine,
            compliance_engine_metrics=ComplianceEngineMetrics(), execution_validator_metrics=ExecutionValidatorMetrics(),
        )
        report = generator.generate("DAILY", [], T0, T0, T0)
        self.assertEqual(report.forward_test_report.recovery_attempt_count, 1)
        self.assertEqual(report.forward_test_report.recovery_success_rate, 1.0)


class TestPeriodConvenienceMethods(unittest.TestCase):
    def test_generate_daily_weekly_monthly_use_correct_period_kind(self):
        generator = _generator()
        daily = generator.generate_daily([], T0)
        weekly = generator.generate_weekly([], T0)
        monthly = generator.generate_monthly([], T0)
        self.assertEqual(daily.period_kind, "DAILY")
        self.assertEqual(weekly.period_kind, "WEEKLY")
        self.assertEqual(monthly.period_kind, "MONTHLY")
        self.assertEqual(daily.window_start, T0.replace(hour=0, minute=0, second=0, microsecond=0))
        self.assertEqual(monthly.window_start, T0.replace(day=1, hour=0, minute=0, second=0, microsecond=0))


if __name__ == "__main__":
    unittest.main()
