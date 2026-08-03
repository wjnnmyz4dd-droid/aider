"""Unit tests: Pair/Strategy/Session Intelligence (ADR-029 §5) -- ranked
by expectancy, ties broken by sample size, never randomized."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.research_engine.pair_intelligence import rank_pairs
from titan_protocol.research_engine.session_intelligence import rank_sessions
from titan_protocol.research_engine.strategy_intelligence import rank_strategies
from titan_protocol.strategy_engine.models import StrategyId
from tests.titan_protocol.research_engine._fixtures import make_config, make_repeating_executed_trades


class TestPairRanking(unittest.TestCase):
    def test_better_pair_ranked_first(self):
        config = make_config(min_sample_size_for_ranking=10)
        good = make_repeating_executed_trades(count=20, win_r=3.0, loss_r=-1.0, win_rate=0.5, pair="EURUSD")
        bad = make_repeating_executed_trades(count=20, win_r=1.0, loss_r=-1.0, win_rate=0.3, pair="GBPUSD")
        rankings = rank_pairs(good + bad, config)
        self.assertEqual(rankings[0].key, "EURUSD")
        self.assertEqual(rankings[0].rank, 1)
        self.assertEqual(rankings[1].key, "GBPUSD")
        self.assertEqual(rankings[1].rank, 2)

    def test_below_min_sample_size_excluded(self):
        config = make_config(min_sample_size_for_ranking=50)
        trades = make_repeating_executed_trades(count=20, pair="EURUSD")
        rankings = rank_pairs(trades, config)
        self.assertEqual(rankings, ())

    def test_average_hold_time_computed(self):
        config = make_config(min_sample_size_for_ranking=5)
        trades = make_repeating_executed_trades(count=10, pair="EURUSD")
        rankings = rank_pairs(trades, config)
        self.assertGreater(rankings[0].average_hold_time_seconds, 0.0)


class TestStrategyRanking(unittest.TestCase):
    def test_ranks_by_strategy_id(self):
        config = make_config(min_sample_size_for_ranking=10)
        trend = make_repeating_executed_trades(count=15, strategy_id=StrategyId.TREND_CONTINUATION, win_rate=0.6)
        range_rev = make_repeating_executed_trades(count=15, strategy_id=StrategyId.RANGE_REVERSAL, win_rate=0.3, win_r=1.0)
        rankings = rank_strategies(trend + range_rev, config)
        self.assertEqual({r.key for r in rankings}, {"TREND_CONTINUATION", "RANGE_REVERSAL"})


class TestSessionRanking(unittest.TestCase):
    def test_ranks_by_session(self):
        config = make_config(min_sample_size_for_ranking=10)
        london = make_repeating_executed_trades(count=15, session=SessionName.LONDON, win_rate=0.6)
        asian = make_repeating_executed_trades(count=15, session=SessionName.ASIAN, win_rate=0.3, win_r=1.0)
        rankings = rank_sessions(london + asian, config)
        self.assertEqual(rankings[0].key, "LONDON")


class TestDeterministicTieBreak(unittest.TestCase):
    def test_equal_expectancy_breaks_tie_by_sample_size_then_key(self):
        config = make_config(min_sample_size_for_ranking=5)
        # Identical expectancy, different sample sizes -- larger sample ranks first.
        small = make_repeating_executed_trades(count=10, pair="AUDUSD", win_rate=0.5, win_r=2.0, loss_r=-1.0)
        large = make_repeating_executed_trades(count=20, pair="NZDUSD", win_rate=0.5, win_r=2.0, loss_r=-1.0)
        rankings = rank_pairs(small + large, config)
        self.assertEqual(rankings[0].key, "NZDUSD")
        self.assertEqual(rankings[0].sample_size, 20)


if __name__ == "__main__":
    unittest.main()
