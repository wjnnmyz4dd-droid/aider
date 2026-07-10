"""Regression tests: fixed input/output anchors for scenarios worked
through during development."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.research_engine.engine import ResearchEngine
from phantom.research_engine.models import ReportPeriod
from tests.phantom.research_engine._fixtures import T0, make_config, make_repeating_executed_trades, make_trade_history


class TestKnownGoodEvaluation(unittest.TestCase):
    def test_30_trade_50pct_win_rate_2r1r_anchors_half_r_expectancy(self):
        config = make_config(min_sample_size_for_ranking=10)
        engine = ResearchEngine(config)
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        snapshot = engine.evaluate(
            make_trade_history(trades), period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40),
        )
        # 15 wins @ +2R, 15 losses @ -1R -> expectancy = (15*2 - 15*1)/30 = 0.5
        self.assertAlmostEqual(snapshot.pair_rankings[0].statistics.rolling_expectancy, 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
