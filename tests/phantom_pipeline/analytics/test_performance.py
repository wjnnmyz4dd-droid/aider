"""Performance statistics tests (ADR-010 §9)."""

from __future__ import annotations

import unittest

from phantom_pipeline.analytics import performance
from phantom_pipeline.analytics.models import FinalOutcome, OutcomeKind, TradeProvenanceRecord
from tests.phantom_pipeline.analytics._fixtures import T0


def _closed_record(pnl: float, mae=None, mfe=None) -> TradeProvenanceRecord:
    return TradeProvenanceRecord(
        schema_version=1, trace_id=f"t-{pnl}", scanner_observation=None, candidate=None, score_result=None,
        risk_decision=None, compliance_decision=None, execution_decision=None, broker_events=(),
        fill_reports=(), position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=FinalOutcome(OutcomeKind.CLOSED, pnl, mae, mfe, "test_close", None, None),
        analytics_version="1.0.0-phase1", collected_at=T0,
    )


def _open_record() -> TradeProvenanceRecord:
    return TradeProvenanceRecord(
        schema_version=1, trace_id="open", scanner_observation=None, candidate=None, score_result=None,
        risk_decision=None, compliance_decision=None, execution_decision=None, broker_events=(),
        fill_reports=(), position_management_decisions=(), position_updates=(),
        position_synchronization_results=(), account_snapshots=(), market_snapshots=(),
        final_outcome=FinalOutcome(OutcomeKind.OPEN, None, None, None, None, None, None),
        analytics_version="1.0.0-phase1", collected_at=T0,
    )


class TestEmptyInput(unittest.TestCase):
    def test_no_records_yields_zero_trade_count(self):
        stats = performance.compute_performance_statistics([], T0)
        self.assertEqual(stats.trade_count, 0)
        self.assertIsNone(stats.win_rate)

    def test_only_open_records_are_excluded(self):
        stats = performance.compute_performance_statistics([_open_record()], T0)
        self.assertEqual(stats.trade_count, 0)


class TestAggregateStatistics(unittest.TestCase):
    def test_win_rate_and_expectancy(self):
        records = [_closed_record(100.0), _closed_record(-50.0), _closed_record(50.0)]
        stats = performance.compute_performance_statistics(records, T0)
        self.assertEqual(stats.trade_count, 3)
        self.assertAlmostEqual(stats.win_rate, 2 / 3)
        self.assertAlmostEqual(stats.expectancy, 100.0 / 3)

    def test_profit_factor(self):
        records = [_closed_record(100.0), _closed_record(-50.0)]
        stats = performance.compute_performance_statistics(records, T0)
        self.assertAlmostEqual(stats.profit_factor, 2.0)

    def test_profit_factor_is_infinite_with_no_losses(self):
        records = [_closed_record(100.0), _closed_record(50.0)]
        stats = performance.compute_performance_statistics(records, T0)
        self.assertEqual(stats.profit_factor, float("inf"))

    def test_average_mae_mfe(self):
        records = [_closed_record(100.0, mae=-20.0, mfe=120.0), _closed_record(50.0, mae=-10.0, mfe=60.0)]
        stats = performance.compute_performance_statistics(records, T0)
        self.assertAlmostEqual(stats.average_mae, -15.0)
        self.assertAlmostEqual(stats.average_mfe, 90.0)

    def test_max_drawdown_from_cumulative_series(self):
        # +100 -> peak 100; -150 -> trough -50, drawdown = 150 from peak.
        records = [_closed_record(100.0), _closed_record(-150.0)]
        stats = performance.compute_performance_statistics(records, T0)
        self.assertAlmostEqual(stats.max_drawdown, 150.0)

    def test_deterministic_for_same_input(self):
        records = [_closed_record(100.0), _closed_record(-50.0), _closed_record(75.0)]
        stats1 = performance.compute_performance_statistics(records, T0)
        stats2 = performance.compute_performance_statistics(records, T0)
        self.assertEqual(stats1, stats2)


if __name__ == "__main__":
    unittest.main()
