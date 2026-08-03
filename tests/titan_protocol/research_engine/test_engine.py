"""Unit tests: `ResearchEngine.evaluate()` orchestration end to end."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.research_engine.engine import ResearchEngine
from titan_protocol.research_engine.models import ReportPeriod
from tests.titan_protocol.research_engine._fixtures import T0, make_config, make_rejected_trade, make_repeating_executed_trades, make_trade_history


class TestEmptyHistory(unittest.TestCase):
    def test_empty_history_produces_warning_and_zero_sample(self):
        engine = ResearchEngine(make_config())
        snapshot = engine.evaluate(
            make_trade_history([]), period=ReportPeriod.CUSTOM, now=T0,
            custom_start=T0 - timedelta(days=1), custom_end=T0,
        )
        self.assertEqual(snapshot.sample_size, 0)
        self.assertTrue(snapshot.warnings)


class TestAllRejectedHistory(unittest.TestCase):
    def test_all_rejected_produces_warning(self):
        engine = ResearchEngine(make_config())
        trades = [make_rejected_trade(index=i) for i in range(5)]
        snapshot = engine.evaluate(
            make_trade_history(trades), period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=10),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=10),
        )
        self.assertEqual(snapshot.sample_size, 0)
        self.assertTrue(any("rejected" in w.lower() for w in snapshot.warnings))


class TestFullEvaluation(unittest.TestCase):
    def test_healthy_history_produces_full_snapshot(self):
        config = make_config(min_sample_size_for_ranking=10)
        engine = ResearchEngine(config)
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        snapshot = engine.evaluate(
            make_trade_history(trades), period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40),
        )
        self.assertEqual(snapshot.sample_size, 30)
        self.assertEqual(len(snapshot.attributions), 13)
        self.assertTrue(snapshot.pair_rankings)
        self.assertIsNotNone(snapshot.execution_quality)
        self.assertIsNotNone(snapshot.market_intelligence_review)
        self.assertIsNotNone(snapshot.risk_review)
        self.assertIsNotNone(snapshot.compliance_effectiveness)

    def test_period_filters_out_of_range_trades(self):
        config = make_config(min_sample_size_for_ranking=5)
        engine = ResearchEngine(config)
        in_range = make_repeating_executed_trades(count=10, start=T0)
        out_of_range = make_repeating_executed_trades(count=10, start=T0 + timedelta(days=365), pair="GBPUSD")
        snapshot = engine.evaluate(
            make_trade_history(in_range + out_of_range), period=ReportPeriod.CUSTOM,
            now=T0 + timedelta(hours=20), custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=20),
        )
        self.assertEqual(snapshot.sample_size, 10)


if __name__ == "__main__":
    unittest.main()
