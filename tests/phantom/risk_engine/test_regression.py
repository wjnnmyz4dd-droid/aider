"""Regression tests: fixed input/output anchors for scenarios worked
through during development."""

from __future__ import annotations

import unittest

from phantom.risk_engine.engine import RiskEngine
from phantom.risk_engine.models import RejectionReason
from tests.phantom.risk_engine._fixtures import make_config, make_evidence_snapshot, make_mi_snapshot, make_strategy_snapshot


class TestKnownGoodEvaluation(unittest.TestCase):
    def test_evidence_score_90_no_history_anchors_fail_closed_floor(self):
        """A 90-score Evidence Snapshot with no trade history anchors to
        the TIER_5 schedule confidence tier but the fail-closed floor
        position size (0.25R) -- this exact combination surfaced during
        development and is anchored here against silent regression."""

        engine = RiskEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
        )
        self.assertTrue(snapshot.approved)
        self.assertEqual(snapshot.confidence_tier.label, "TIER_5")
        self.assertAlmostEqual(snapshot.approved_risk_r, 0.25, places=6)

    def test_below_gate_always_rejects_with_no_other_computation(self):
        engine = RiskEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=64.9), make_mi_snapshot(), make_strategy_snapshot(),
        )
        self.assertFalse(snapshot.approved)
        self.assertEqual(snapshot.rejection_reason, RejectionReason.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(snapshot.confidence_tier)
        self.assertIsNone(snapshot.exposure_summary)
        self.assertIsNone(snapshot.correlation_status)
        self.assertIsNone(snapshot.statistical_metrics)
        self.assertIsNone(snapshot.monte_carlo)
        self.assertIsNone(snapshot.recommended_position_size)
        self.assertIsNone(snapshot.reservation_id)


if __name__ == "__main__":
    unittest.main()
