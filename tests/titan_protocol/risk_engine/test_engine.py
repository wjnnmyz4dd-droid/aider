"""Unit tests: `RiskEngine.evaluate()`/`evaluate_batch()` orchestration
end to end -- gate, strategy gate, sizing, exposure, and the atomic
reservation."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import RejectionReason
from tests.titan_protocol.risk_engine._fixtures import (
    T0,
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_open_position,
    make_portfolio_state,
    make_repeating_trade_history,
    make_strategy_snapshot,
)


class TestSymbolMismatchRaises(unittest.TestCase):
    def test_evidence_symbol_mismatch_raises(self):
        engine = RiskEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate("EURUSD", make_evidence_snapshot(symbol="GBPUSD"), make_mi_snapshot(), make_strategy_snapshot())

    def test_market_intelligence_pair_mismatch_raises(self):
        engine = RiskEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot(pair="GBPUSD"), make_strategy_snapshot())

    def test_strategy_pair_mismatch_raises(self):
        engine = RiskEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate("EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(pair="GBPUSD"))


class TestGateRejections(unittest.TestCase):
    def test_low_evidence_score_rejects_before_anything_else(self):
        engine = RiskEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=50.0), make_mi_snapshot(), make_strategy_snapshot(),
        )
        self.assertFalse(snapshot.approved)
        self.assertEqual(snapshot.rejection_reason, RejectionReason.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(snapshot.confidence_tier)
        self.assertIsNone(snapshot.statistical_metrics)

    def test_rejected_strategy_snapshot_rejects(self):
        engine = RiskEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(),
            make_strategy_snapshot(rejected=True),
        )
        self.assertFalse(snapshot.approved)
        self.assertEqual(snapshot.rejection_reason, RejectionReason.NO_QUALIFIED_STRATEGY)


class TestApprovalPath(unittest.TestCase):
    def test_qualifying_evidence_and_strategy_approves(self):
        engine = RiskEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
        )
        self.assertTrue(snapshot.approved)
        self.assertIsNotNone(snapshot.recommended_position_size)
        self.assertGreater(snapshot.approved_risk_r, 0.0)
        self.assertIsNotNone(snapshot.reservation_id)
        self.assertTrue(snapshot.reasons)

    def test_reservation_is_recorded_in_exposure_on_next_call(self):
        engine = RiskEngine(make_config())
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        first = engine.evaluate("EURUSD", evidence, mi, strategy, portfolio_state=make_portfolio_state([]))
        second = engine.evaluate("EURUSD", evidence, mi, strategy, portfolio_state=make_portfolio_state([]))
        self.assertGreaterEqual(second.exposure_summary.pending_reservation_total_r, first.approved_risk_r)

    def test_release_reservation_removes_it_from_exposure(self):
        engine = RiskEngine(make_config())
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        first = engine.evaluate("EURUSD", evidence, mi, strategy, portfolio_state=make_portfolio_state([]))
        self.assertTrue(engine.release_reservation(first.reservation_id))
        second = engine.evaluate("EURUSD", evidence, mi, strategy, portfolio_state=make_portfolio_state([]))
        self.assertEqual(second.exposure_summary.pending_reservation_total_r, 0.0)


class TestFailClosedWithSufficientHistory(unittest.TestCase):
    def test_sufficient_history_lifts_the_fail_closed_cap(self):
        config = make_config()
        engine = RiskEngine(config)
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi = make_mi_snapshot()
        strategy = make_strategy_snapshot()
        history = make_repeating_trade_history(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        snapshot = engine.evaluate("EURUSD", evidence, mi, strategy, trade_history=history)
        self.assertTrue(snapshot.statistical_metrics.sufficient_data)
        self.assertIsNotNone(snapshot.monte_carlo)


class TestEvaluateBatch(unittest.TestCase):
    def test_batch_evaluates_every_pair_sorted(self):
        engine = RiskEngine(make_config())
        evidence = make_evidence_snapshot(evidence_score=90.0)
        mi_eur = make_mi_snapshot(pair="EURUSD")
        mi_gbp = make_mi_snapshot(pair="GBPUSD")
        pairs = {
            "GBPUSD": (make_evidence_snapshot(symbol="GBPUSD", evidence_score=90.0), mi_gbp, make_strategy_snapshot(pair="GBPUSD")),
            "EURUSD": (evidence, mi_eur, make_strategy_snapshot(pair="EURUSD")),
        }
        results = engine.evaluate_batch(pairs)
        self.assertEqual([r.pair for r in results], ["EURUSD", "GBPUSD"])


if __name__ == "__main__":
    unittest.main()
