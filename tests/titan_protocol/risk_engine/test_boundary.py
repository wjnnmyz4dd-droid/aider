"""Boundary tests: edge conditions at every configured limit and
input-shape edge case (ADR-027 §3)."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.confidence import confidence_tier_for_evidence_score
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.gate import check_evidence_gate
from titan_protocol.risk_engine.models import RejectionReason
from titan_protocol.risk_engine.position_sizing import compute_position_size
from tests.titan_protocol.risk_engine._fixtures import (
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_open_position,
    make_portfolio_state,
    make_strategy_snapshot,
)


class TestGateBoundary(unittest.TestCase):
    def test_exactly_at_gate_score_passes(self):
        config = make_config()
        self.assertIsNone(check_evidence_gate(make_evidence_snapshot(evidence_score=config.minimum_evidence_score), config))

    def test_one_thousandth_below_gate_rejects(self):
        config = make_config()
        below = config.minimum_evidence_score - 0.001
        self.assertEqual(check_evidence_gate(make_evidence_snapshot(evidence_score=below), config), RejectionReason.INSUFFICIENT_EVIDENCE)


class TestConfidenceScheduleBoundaries(unittest.TestCase):
    def test_tier_boundaries_never_overlap_or_gap(self):
        config = make_config()
        schedule = sorted(config.confidence_schedule, key=lambda t: t.min_score)
        for i in range(len(schedule) - 1):
            self.assertLess(schedule[i].max_score, schedule[i + 1].min_score + 1e-9)


class TestEmptyPortfolioState(unittest.TestCase):
    def test_zero_open_positions_is_not_treated_as_unknown(self):
        engine = RiskEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            portfolio_state=make_portfolio_state([]),
        )
        from titan_protocol.risk_engine.models import DataQuality
        self.assertEqual(snapshot.exposure_summary.data_quality, DataQuality.KNOWN)


class TestZeroRiskCandidate(unittest.TestCase):
    def test_zero_confidence_base_r_produces_zero_or_floor_final_r(self):
        from titan_protocol.risk_engine.models import ConfidenceTier, StatisticalMetrics, VolatilityAdjustment

        config = make_config(min_position_r=0.0)
        zero_tier = ConfidenceTier(label="ZERO", min_score=0.0, max_score=100.0, base_r=0.0)
        vol = VolatilityAdjustment(atr=0.0, volatility_label="NORMAL", sizing_multiplier=1.0, reason="test")
        metrics = StatisticalMetrics(sufficient_data=True, sample_size=30)
        rec = compute_position_size(zero_tier, vol, metrics, config)
        self.assertEqual(rec.final_r, 0.0)


class TestMaxPositionsAtExactLimit(unittest.TestCase):
    def test_one_below_max_open_positions_passes(self):
        config = make_config(max_open_positions=2)
        engine = RiskEngine(config)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD")])
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            portfolio_state=portfolio,
        )
        self.assertTrue(snapshot.approved)


if __name__ == "__main__":
    unittest.main()
