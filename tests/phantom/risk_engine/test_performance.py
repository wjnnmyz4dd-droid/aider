"""Performance, stress, and concurrency tests: 28+ pairs, thread safety
under concurrent `evaluate()` calls, and the reservation ledger's
atomicity under load."""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from phantom.risk_engine.engine import RiskEngine
from tests.phantom.risk_engine._fixtures import (
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_repeating_trade_history,
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


class TestBatchPerformance(unittest.TestCase):
    def test_28_plus_pairs_evaluated_in_one_batch_call(self):
        self.assertGreaterEqual(len(PAIRS), 28)
        engine = RiskEngine(make_config())
        pairs = {
            p: (make_evidence_snapshot(symbol=p, evidence_score=90.0), make_mi_snapshot(pair=p), make_strategy_snapshot(pair=p))
            for p in PAIRS
        }

        start = time.perf_counter()
        results = engine.evaluate_batch(pairs)
        elapsed = time.perf_counter() - start

        self.assertEqual(len(results), len(PAIRS))
        self.assertLess(elapsed, 5.0, f"28+ pair batch took {elapsed:.2f}s")


class TestStressWithTradeHistory(unittest.TestCase):
    def test_28_pairs_with_full_statistics_and_monte_carlo_within_budget(self):
        engine = RiskEngine(make_config(monte_carlo_simulations=200, risk_of_ruin_simulations=200))
        history = make_repeating_trade_history(count=50, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        pairs = {
            p: (make_evidence_snapshot(symbol=p, evidence_score=90.0), make_mi_snapshot(pair=p), make_strategy_snapshot(pair=p))
            for p in PAIRS
        }

        start = time.perf_counter()
        results = engine.evaluate_batch(pairs, trade_history=history)
        elapsed = time.perf_counter() - start

        self.assertEqual(len(results), len(PAIRS))
        self.assertTrue(all(r.statistical_metrics.sufficient_data for r in results))
        self.assertLess(elapsed, 10.0, f"28-pair batch with full statistics took {elapsed:.2f}s")


class TestConcurrentEvaluate(unittest.TestCase):
    def test_concurrent_evaluate_across_many_threads_no_errors(self):
        engine = RiskEngine(make_config())
        snapshots = {
            p: (make_evidence_snapshot(symbol=p, evidence_score=90.0), make_mi_snapshot(pair=p), make_strategy_snapshot(pair=p))
            for p in PAIRS
        }
        errors = []

        def worker(pair):
            try:
                evidence, mi, strategy = snapshots[pair]
                for _ in range(5):
                    engine.evaluate(pair, evidence, mi, strategy)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=len(PAIRS)) as pool:
            list(pool.map(worker, PAIRS))

        self.assertEqual(errors, [])

    def test_concurrent_evaluate_never_exceeds_portfolio_heat_limit(self):
        """N threads race to get the same pair approved against a tight
        portfolio heat limit -- the atomic reservation must ensure total
        approved risk never exceeds the configured limit (ADR-027 Hard
        Rule 5)."""

        config = make_config(portfolio_heat_limit_r=2.0, max_concurrent_risk_r=2.0, max_position_r=0.25, min_position_r=0.25)
        engine = RiskEngine(config)
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()

        def worker(_):
            from phantom.risk_engine.models import PortfolioState
            return engine.evaluate("EURUSD", evidence, mi, strategy, portfolio_state=PortfolioState(open_positions=()))

        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(worker, range(64)))

        total_approved = sum(r.approved_risk_r for r in results if r.approved)
        self.assertLessEqual(total_approved, config.portfolio_heat_limit_r + 1e-9)


if __name__ == "__main__":
    unittest.main()
