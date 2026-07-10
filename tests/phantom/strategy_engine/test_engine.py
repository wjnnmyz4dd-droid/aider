"""Integration tests for `StrategyEngine.evaluate()`/`evaluate_batch()`."""

from __future__ import annotations

import unittest

from phantom.strategy_engine.engine import StrategyEngine
from phantom.strategy_engine.metrics import StrategyEngineMetrics
from phantom.strategy_engine.models import StrategySnapshot
from tests.phantom.strategy_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot


class TestEvaluate(unittest.TestCase):
    def test_returns_a_fully_populated_snapshot(self):
        engine = StrategyEngine(make_config())
        snapshot = engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        self.assertIsInstance(snapshot, StrategySnapshot)
        self.assertEqual(snapshot.pair, "EURUSD")
        self.assertEqual(len(snapshot.all_qualifications), 5)

    def test_evidence_symbol_mismatch_raises(self):
        engine = StrategyEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate("GBPUSD", make_evidence_snapshot(symbol="EURUSD"), make_mi_snapshot(pair="EURUSD"))

    def test_market_intelligence_pair_mismatch_raises(self):
        engine = StrategyEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate("EURUSD", make_evidence_snapshot(symbol="EURUSD"), make_mi_snapshot(pair="GBPUSD"))

    def test_metrics_recorded_on_evaluate(self):
        metrics = StrategyEngineMetrics()
        engine = StrategyEngine(make_config(), metrics=metrics)
        engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot())
        self.assertEqual(metrics.evaluation_count, 2)
        self.assertEqual(metrics.rejection_count, 2)  # nothing qualifies with plain default fixtures


class TestEvaluateBatch(unittest.TestCase):
    def test_evaluates_multiple_pairs(self):
        engine = StrategyEngine(make_config())
        pairs = {
            "EURUSD": (make_evidence_snapshot(symbol="EURUSD"), make_mi_snapshot(pair="EURUSD")),
            "GBPUSD": (make_evidence_snapshot(symbol="GBPUSD"), make_mi_snapshot(pair="GBPUSD")),
        }
        results = engine.evaluate_batch(pairs)
        self.assertEqual(len(results), 2)
        self.assertEqual({r.pair for r in results}, {"EURUSD", "GBPUSD"})

    def test_batch_metric_counts_once_per_call(self):
        metrics = StrategyEngineMetrics()
        engine = StrategyEngine(make_config(), metrics=metrics)
        pairs = {
            "EURUSD": (make_evidence_snapshot(symbol="EURUSD"), make_mi_snapshot(pair="EURUSD")),
            "GBPUSD": (make_evidence_snapshot(symbol="GBPUSD"), make_mi_snapshot(pair="GBPUSD")),
        }
        engine.evaluate_batch(pairs)
        self.assertEqual(metrics.batch_evaluation_count, 1)
        self.assertEqual(metrics.evaluation_count, 2)


if __name__ == "__main__":
    unittest.main()
