"""Concurrency category: `ValidationEngine` holds no mutable state, so
concurrent `evaluate()` calls against one shared instance must never
error and must always agree (ADR-030 §2.6)."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from titan_protocol.validation_engine.config import ValidationEngineConfig
from titan_protocol.validation_engine.engine import ValidationEngine
from tests.titan_protocol.validation_engine._fixtures import (
    T0,
    make_execution_record,
    make_repeating_executed_trades,
    make_run,
    make_scenario,
    make_trade_history,
)


class TestConcurrentEvaluate(unittest.TestCase):
    def test_concurrent_evaluate_across_many_threads_no_errors(self):
        engine = ValidationEngine(ValidationEngineConfig())
        run = make_run([make_scenario(execution=make_execution_record())])
        history = make_trade_history(make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5))
        errors = []

        def worker(_):
            try:
                engine.evaluate(run, history, now=T0)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_produces_consistent_results(self):
        engine = ValidationEngine(ValidationEngineConfig())
        run = make_run([make_scenario(execution=make_execution_record())])
        history = make_trade_history(make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5))
        results = []

        def worker(_):
            results.append(engine.evaluate(run, history, now=T0))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(32)))

        first = results[0]
        for result in results:
            self.assertEqual(result, first)


if __name__ == "__main__":
    unittest.main()
