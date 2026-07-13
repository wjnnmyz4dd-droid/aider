"""Determinism tests: repeated calls, two independent engine instances,
and `evaluate_batch()` vs. individual calls all agree byte-for-byte
(ADR-028 Hard Rule 6 -- pure deterministic logic)."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.engine import ComplianceEngine
from tests.titan_protocol.compliance_engine._fixtures import (
    T0,
    make_account_state,
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_portfolio_state,
    make_risk_snapshot,
    make_strategy_snapshot,
)


class TestRepeatedCallsAreIdentical(unittest.TestCase):
    def test_same_engine_repeated_calls_identical(self):
        engine = ComplianceEngine(make_config())
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        risk = make_risk_snapshot()
        portfolio = make_portfolio_state()
        account = make_account_state()

        first = engine.evaluate("EURUSD", evidence, mi, strategy, risk, portfolio, account, now=T0)
        second = engine.evaluate("EURUSD", evidence, mi, strategy, risk, portfolio, account, now=T0)

        self.assertEqual(first, second)


class TestIndependentEnginesAgree(unittest.TestCase):
    def test_two_fresh_engines_produce_identical_results(self):
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        risk = make_risk_snapshot()
        portfolio = make_portfolio_state()
        account = make_account_state()

        engine_a = ComplianceEngine(make_config())
        engine_b = ComplianceEngine(make_config())
        result_a = engine_a.evaluate("EURUSD", evidence, mi, strategy, risk, portfolio, account, now=T0)
        result_b = engine_b.evaluate("EURUSD", evidence, mi, strategy, risk, portfolio, account, now=T0)

        self.assertEqual(result_a, result_b)


class TestBatchMatchesIndividual(unittest.TestCase):
    def test_batch_matches_individual_call(self):
        config = make_config()
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        risk = make_risk_snapshot()
        portfolio = make_portfolio_state()
        account = make_account_state()

        individual_engine = ComplianceEngine(config)
        individual = individual_engine.evaluate("EURUSD", evidence, mi, strategy, risk, portfolio, account, now=T0)

        batch_engine = ComplianceEngine(config)
        batch_results = batch_engine.evaluate_batch({"EURUSD": (evidence, mi, strategy, risk)}, portfolio, account, now=T0)

        self.assertEqual(individual, batch_results[0])


if __name__ == "__main__":
    unittest.main()
