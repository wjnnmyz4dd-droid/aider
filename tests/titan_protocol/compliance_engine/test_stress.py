"""Stress/performance tests: 28+ pairs in one `evaluate_batch()` call
(ADR-028 §10)."""

from __future__ import annotations

import time
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

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF",
    "CHFJPY",
]


class TestBatchStress(unittest.TestCase):
    def test_28_plus_pairs_evaluated_in_one_batch_call(self):
        self.assertGreaterEqual(len(PAIRS), 28)
        engine = ComplianceEngine(make_config())
        pairs = {
            p: (
                make_evidence_snapshot(symbol=p, evidence_score=90.0), make_mi_snapshot(pair=p),
                make_strategy_snapshot(pair=p), make_risk_snapshot(pair=p),
            )
            for p in PAIRS
        }

        start = time.perf_counter()
        results = engine.evaluate_batch(pairs, make_portfolio_state(), make_account_state(), now=T0)
        elapsed = time.perf_counter() - start

        self.assertEqual(len(results), len(PAIRS))
        self.assertLess(elapsed, 5.0, f"28+ pair batch took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
