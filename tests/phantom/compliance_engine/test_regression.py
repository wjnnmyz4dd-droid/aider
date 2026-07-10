"""Regression tests: fixed input/output anchors for scenarios worked
through during development."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.engine import ComplianceEngine
from phantom.compliance_engine.models import ComplianceDecision
from tests.phantom.compliance_engine._fixtures import (
    T0,
    make_account_state,
    make_config,
    make_evidence_snapshot,
    make_mi_snapshot,
    make_portfolio_state,
    make_risk_snapshot,
    make_strategy_snapshot,
)


class TestKnownGoodEvaluation(unittest.TestCase):
    def test_healthy_account_full_evidence_score_approves_at_full_size(self):
        engine = ComplianceEngine(make_config())
        risk = make_risk_snapshot(approved_risk_r=1.25)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            risk, make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)
        self.assertAlmostEqual(snapshot.approved_size_r, 1.25, places=6)
        self.assertAlmostEqual(snapshot.compliance_score, 100.0, places=6)

    def test_75_pct_daily_loss_with_low_evidence_score_anchors_reject(self):
        """A known scenario worked through during development: 75% of
        the daily loss limit consumed lands in the 70-80% band, which
        requires evidence >= 85; a 70-point evidence score fails that
        gate and must reject, not merely reduce."""

        engine = ComplianceEngine(make_config())
        account = make_account_state(account_balance=96_250.0, daily_starting_balance=100_000.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=70.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.approved_size_r, 0.0)


if __name__ == "__main__":
    unittest.main()
