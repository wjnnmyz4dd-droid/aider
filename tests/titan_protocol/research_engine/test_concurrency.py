"""Concurrency tests: `ResearchEngine` holds no mutable state, so
concurrent `evaluate()` calls against one shared instance must never
error and must always agree (ADR-029 Hard Rule 2)."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from titan_protocol.research_engine.engine import ResearchEngine
from titan_protocol.research_engine.models import ReportPeriod
from tests.titan_protocol.research_engine._fixtures import T0, make_config, make_repeating_executed_trades, make_trade_history


class TestConcurrentEvaluate(unittest.TestCase):
    def test_concurrent_evaluate_across_many_threads_no_errors(self):
        config = make_config(min_sample_size_for_ranking=10)
        engine = ResearchEngine(config)
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        history = make_trade_history(trades)
        errors = []

        def worker(_):
            try:
                engine.evaluate(
                    history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40),
                    custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40),
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_produces_consistent_results(self):
        config = make_config(min_sample_size_for_ranking=10)
        engine = ResearchEngine(config)
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        history = make_trade_history(trades)
        results = []

        def worker(_):
            results.append(engine.evaluate(
                history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(hours=40),
                custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(hours=40),
            ))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        first = results[0]
        for result in results:
            self.assertEqual(result, first)


if __name__ == "__main__":
    unittest.main()
