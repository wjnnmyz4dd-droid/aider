"""Integration tests for `EvidenceEngine.evaluate()` / `evaluate_batch()`."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.metrics import EvidenceEngineMetrics
from titan_protocol.evidence_engine.models import EvidenceReport, PairRanking
from tests.titan_protocol.evidence_engine._fixtures import STRUCTURE_SAMPLE, make_bars, make_config


class TestEvaluate(unittest.TestCase):
    def test_returns_a_fully_populated_report(self):
        engine = EvidenceEngine(make_config())
        bars = make_bars(STRUCTURE_SAMPLE, symbol="EURUSD")
        report = engine.evaluate("EURUSD", bars)
        self.assertIsInstance(report, EvidenceReport)
        self.assertEqual(report.symbol, "EURUSD")
        self.assertTrue(0.0 <= report.score.composite <= 100.0)
        self.assertEqual(len(report.score.components), 7)
        self.assertTrue(report.confidence_explanation)

    def test_empty_bars_raises(self):
        engine = EvidenceEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate("EURUSD", [])

    def test_uses_last_bar_timestamp_when_now_not_supplied(self):
        engine = EvidenceEngine(make_config())
        bars = make_bars(STRUCTURE_SAMPLE, symbol="EURUSD")
        report = engine.evaluate("EURUSD", bars)
        self.assertEqual(report.generated_at, bars[-1].timestamp)

    def test_metrics_recorded_on_evaluate(self):
        metrics = EvidenceEngineMetrics()
        engine = EvidenceEngine(make_config(), metrics=metrics)
        bars = make_bars(STRUCTURE_SAMPLE, symbol="EURUSD")
        engine.evaluate("EURUSD", bars)
        engine.evaluate("EURUSD", bars)
        self.assertEqual(metrics.evaluation_count, 2)


class TestEvaluateBatch(unittest.TestCase):
    def test_ranks_multiple_pairs(self):
        engine = EvidenceEngine(make_config())
        pairs = {
            "EURUSD": make_bars(STRUCTURE_SAMPLE, symbol="EURUSD"),
            "GBPUSD": make_bars(STRUCTURE_SAMPLE, symbol="GBPUSD"),
            "USDJPY": make_bars(STRUCTURE_SAMPLE, symbol="USDJPY"),
        }
        ranking = engine.evaluate_batch(pairs)
        self.assertEqual(len(ranking), 3)
        self.assertTrue(all(isinstance(r, PairRanking) for r in ranking))
        self.assertEqual([r.rank for r in ranking], [1, 2, 3])
        symbols = {r.symbol for r in ranking}
        self.assertEqual(symbols, {"EURUSD", "GBPUSD", "USDJPY"})

    def test_batch_evaluation_metric_counts_once_per_call_not_per_pair(self):
        metrics = EvidenceEngineMetrics()
        engine = EvidenceEngine(make_config(), metrics=metrics)
        pairs = {sym: make_bars(STRUCTURE_SAMPLE, symbol=sym) for sym in ("EURUSD", "GBPUSD")}
        engine.evaluate_batch(pairs)
        self.assertEqual(metrics.batch_evaluation_count, 1)
        self.assertEqual(metrics.evaluation_count, 2)


if __name__ == "__main__":
    unittest.main()
