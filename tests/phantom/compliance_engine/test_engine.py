"""Unit tests: `ComplianceEngine.evaluate()`/`evaluate_batch()`
orchestration end to end -- the full reject cascade, the graduated
reduction path, and the approve path."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.engine import ComplianceEngine
from phantom.compliance_engine.models import ComplianceDecision, ComplianceLockState, ComplianceRuleId
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


class TestPairMismatchRaises(unittest.TestCase):
    def test_evidence_symbol_mismatch_raises(self):
        engine = ComplianceEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate(
                "EURUSD", make_evidence_snapshot(symbol="GBPUSD"), make_mi_snapshot(), make_strategy_snapshot(),
                make_risk_snapshot(), make_portfolio_state(), make_account_state(),
            )

    def test_risk_pair_mismatch_raises(self):
        engine = ComplianceEngine(make_config())
        with self.assertRaises(ValueError):
            engine.evaluate(
                "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
                make_risk_snapshot(pair="GBPUSD"), make_portfolio_state(), make_account_state(),
            )


class TestUpstreamAuthorityGates(unittest.TestCase):
    def test_emergency_stop_rejects_first(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(emergency_stop_active=True)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.audit_entry.triggered_rules, (ComplianceRuleId.EMERGENCY_STOP_ACTIVE,))

    def test_compliance_lock_rejects(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(compliance_lock=ComplianceLockState(active=True, reason="prior daily loss"))
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.audit_entry.triggered_rules, (ComplianceRuleId.COMPLIANCE_LOCK_ACTIVE,))

    def test_risk_not_approved_rejects(self):
        engine = ComplianceEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved=False), make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.audit_entry.triggered_rules, (ComplianceRuleId.RISK_NOT_APPROVED,))

    def test_no_qualified_strategy_rejects(self):
        engine = ComplianceEngine(make_config())
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(rejected=True),
            make_risk_snapshot(), make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.audit_entry.triggered_rules, (ComplianceRuleId.NO_QUALIFIED_STRATEGY,))

    def test_never_increases_above_risk_engines_recommendation(self):
        engine = ComplianceEngine(make_config())
        risk = make_risk_snapshot(approved_risk_r=0.5)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            risk, make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertLessEqual(snapshot.approved_size_r, 0.5)


class TestApprovePath(unittest.TestCase):
    def test_healthy_account_approves_full_size(self):
        engine = ComplianceEngine(make_config())
        risk = make_risk_snapshot(approved_risk_r=1.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            risk, make_portfolio_state(), make_account_state(), now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)
        self.assertEqual(snapshot.approved_size_r, 1.0)
        self.assertTrue(snapshot.ready_for_bridge)


class TestEvaluateBatch(unittest.TestCase):
    def test_batch_evaluates_every_pair_sorted(self):
        engine = ComplianceEngine(make_config())
        pairs = {
            "GBPUSD": (
                make_evidence_snapshot(symbol="GBPUSD", evidence_score=90.0), make_mi_snapshot(pair="GBPUSD"),
                make_strategy_snapshot(pair="GBPUSD"), make_risk_snapshot(pair="GBPUSD"),
            ),
            "EURUSD": (
                make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(), make_risk_snapshot(),
            ),
        }
        results = engine.evaluate_batch(pairs, make_portfolio_state(), make_account_state())
        self.assertEqual([r.pair for r in results], ["EURUSD", "GBPUSD"])


if __name__ == "__main__":
    unittest.main()
