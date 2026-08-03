"""Explainability tests: every decision -- approve, reduce, or reject --
carries a reason, triggered rule(s), original/final size, and a
timestamped audit entry (ADR-028 §7, Hard Rule 7)."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceDecision
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


class TestApprovalExplainability(unittest.TestCase):
    def test_approval_carries_reason_and_audit_entry(self):
        engine = ComplianceEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertTrue(snapshot.reason)
        self.assertEqual(snapshot.audit_entry.decision, ComplianceDecision.APPROVE)
        self.assertEqual(snapshot.audit_entry.original_size_r, snapshot.original_size_r)
        self.assertEqual(snapshot.audit_entry.final_size_r, snapshot.approved_size_r)
        self.assertEqual(snapshot.audit_entry.timestamp, T0)


class TestReductionExplainability(unittest.TestCase):
    def test_reduction_carries_reason_and_triggered_rules(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_balance=97_000.0, daily_starting_balance=100_000.0)  # 60% band
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REDUCE)
        self.assertTrue(snapshot.reason)
        self.assertTrue(snapshot.audit_entry.triggered_rules)
        self.assertGreater(snapshot.reduction_pct, 0.0)


class TestRejectionExplainability(unittest.TestCase):
    def test_rejection_carries_reason_and_triggered_rule(self):
        engine = ComplianceEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved=False), make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertTrue(snapshot.reason)
        self.assertTrue(snapshot.audit_entry.triggered_rules)
        self.assertEqual(snapshot.approved_size_r, 0.0)
        self.assertFalse(snapshot.ready_for_bridge)


class TestComplianceScoreAlwaysPresent(unittest.TestCase):
    def test_score_present_on_every_path(self):
        engine = ComplianceEngine(make_config())
        approve = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), make_account_state(), now=T0,
        )
        reject = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved=False), make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertIsInstance(approve.compliance_score, float)
        self.assertIsInstance(reject.compliance_score, float)


if __name__ == "__main__":
    unittest.main()
