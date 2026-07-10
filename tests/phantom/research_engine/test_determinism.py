"""Determinism tests: repeated calls, two independent engine instances,
and stable ordering of recommendations/rankings/attributions -- all
produce byte-identical output (ADR-029 Hard Rule 2)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.research_engine.engine import ResearchEngine
from phantom.research_engine.models import ReportPeriod
from tests.phantom.research_engine._fixtures import T0, make_config, make_repeating_executed_trades, make_trade_history


class TestRepeatedCallsAreIdentical(unittest.TestCase):
    def test_same_engine_repeated_calls_identical(self):
        engine = ResearchEngine(make_config(min_sample_size_for_ranking=10))
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        history = make_trade_history(trades)
        kwargs = dict(period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40), custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40))

        first = engine.evaluate(history, **kwargs)
        second = engine.evaluate(history, **kwargs)
        self.assertEqual(first, second)


class TestIndependentEnginesAgree(unittest.TestCase):
    def test_two_fresh_engines_produce_identical_snapshots(self):
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        history = make_trade_history(trades)
        kwargs = dict(period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40), custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40))

        engine_a = ResearchEngine(make_config(min_sample_size_for_ranking=10))
        engine_b = ResearchEngine(make_config(min_sample_size_for_ranking=10))
        result_a = engine_a.evaluate(history, **kwargs)
        result_b = engine_b.evaluate(history, **kwargs)
        self.assertEqual(result_a, result_b)


if __name__ == "__main__":
    unittest.main()
