"""Concurrency tests: `ComplianceEngine` holds no mutable state, so
concurrent `evaluate()` calls against one shared instance must never
error and must always agree (ADR-028 §3, Hard Rule 6)."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

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

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF",
]


class TestConcurrentEvaluate(unittest.TestCase):
    def test_concurrent_evaluate_across_many_threads_no_errors(self):
        engine = ComplianceEngine(make_config())
        inputs = {
            p: (
                make_evidence_snapshot(symbol=p, evidence_score=90.0), make_mi_snapshot(pair=p),
                make_strategy_snapshot(pair=p), make_risk_snapshot(pair=p),
            )
            for p in PAIRS
        }
        errors = []

        def worker(pair):
            try:
                evidence, mi, strategy, risk = inputs[pair]
                for _ in range(10):
                    engine.evaluate(pair, evidence, mi, strategy, risk, make_portfolio_state(), make_account_state(), now=T0)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=len(PAIRS)) as pool:
            list(pool.map(worker, PAIRS))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_of_same_pair_is_consistent(self):
        engine = ComplianceEngine(make_config())
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        risk = make_risk_snapshot()
        portfolio = make_portfolio_state()
        account = make_account_state()
        results = []

        def worker(_):
            results.append(engine.evaluate("EURUSD", evidence, mi, strategy, risk, portfolio, account, now=T0))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(64)))

        first = results[0]
        for result in results:
            self.assertEqual(result.decision, first.decision)
            self.assertEqual(result.approved_size_r, first.approved_size_r)


if __name__ == "__main__":
    unittest.main()
