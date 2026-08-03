"""Determinism tests: repeated calls, two independent engine instances,
and `evaluate_batch()` all produce byte-identical output (outside the
seeded-and-isolated Monte Carlo path, which is itself deterministic per
seed -- ADR-027 Hard Rule 7)."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.engine import RiskEngine
from tests.titan_protocol.risk_engine._fixtures import (
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_repeating_trade_history,
    make_strategy_snapshot,
)


class TestRepeatedCallsAreIdentical(unittest.TestCase):
    def test_same_engine_repeated_calls_identical(self):
        engine = RiskEngine(make_config())
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)

        first = engine.evaluate("EURUSD", evidence, mi, strategy, trade_history=history)
        second = engine.evaluate("EURUSD", evidence, mi, strategy, trade_history=history)

        # reservation_id increments per call -- compare everything else.
        self.assertEqual(first.approved, second.approved)
        self.assertEqual(first.approved_risk_r, second.approved_risk_r)
        self.assertEqual(first.confidence_tier, second.confidence_tier)
        self.assertEqual(first.statistical_metrics, second.statistical_metrics)
        self.assertEqual(first.monte_carlo, second.monte_carlo)
        self.assertEqual(first.recommended_position_size, second.recommended_position_size)


class TestIndependentEnginesAgree(unittest.TestCase):
    def test_two_fresh_engines_produce_identical_recommendations(self):
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)

        engine_a = RiskEngine(make_config())
        engine_b = RiskEngine(make_config())
        result_a = engine_a.evaluate("EURUSD", evidence, mi, strategy, trade_history=history)
        result_b = engine_b.evaluate("EURUSD", evidence, mi, strategy, trade_history=history)

        self.assertEqual(result_a.approved_risk_r, result_b.approved_risk_r)
        self.assertEqual(result_a.monte_carlo, result_b.monte_carlo)
        self.assertEqual(result_a.statistical_metrics, result_b.statistical_metrics)


class TestBatchIsDeterministic(unittest.TestCase):
    def test_batch_matches_individual_calls(self):
        config = make_config()
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()

        individual_engine = RiskEngine(config)
        individual = individual_engine.evaluate("EURUSD", evidence, mi, strategy)

        batch_engine = RiskEngine(config)
        batch_results = batch_engine.evaluate_batch({"EURUSD": (evidence, mi, strategy)})

        self.assertEqual(individual.approved_risk_r, batch_results[0].approved_risk_r)
        self.assertEqual(individual.confidence_tier, batch_results[0].confidence_tier)


if __name__ == "__main__":
    unittest.main()
