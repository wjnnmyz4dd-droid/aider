"""Unit tests: `ComplianceEngine.evaluate()`/`evaluate_batch()`
orchestration end to end -- the full reject cascade, the graduated
reduction path, and the approve path."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceDecision, ComplianceLockState, ComplianceRuleId
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

    def test_stale_account_state_rejects_before_risk_check(self):
        """Default profile's max_account_state_age_seconds is 30.0 --
        an age past that must reject with ACCOUNT_STATE_STALE, and must
        do so before risk/strategy/market-condition gates run (matches
        EMERGENCY_STOP_ACTIVE/COMPLIANCE_LOCK_ACTIVE's own early-gate
        placement, since a stale balance makes every downstream
        daily-loss/drawdown evaluation untrustworthy)."""
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_report_age_seconds=45.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved=False), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.audit_entry.triggered_rules, (ComplianceRuleId.ACCOUNT_STATE_STALE,))

    def test_account_state_exactly_at_threshold_is_not_stale(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_report_age_seconds=30.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved_risk_r=1.0), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)

    def test_account_state_fresh_within_threshold_approves(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_report_age_seconds=5.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved_risk_r=1.0), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)

    def test_none_age_never_gates_backward_compatible(self):
        """Every existing caller/test that never passes
        account_report_age_seconds (the default, None) must keep its old,
        unaffected behavior -- the staleness gate only ever fires when a
        real age is supplied."""
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_report_age_seconds=None)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved_risk_r=1.0), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)

    def test_resumes_automatically_once_a_fresh_report_arrives(self):
        """No special 'resume' logic exists or is needed -- each
        evaluate() call is a pure function of its inputs (ADR-028 Hard
        Rule 6), so a stale-then-fresh sequence of ages on the exact same
        engine/account produces REJECT then APPROVE with zero persisted
        state to reset."""
        engine = ComplianceEngine(make_config())
        stale_account = make_account_state(account_report_age_seconds=60.0)
        stale_snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved_risk_r=1.0), make_portfolio_state(), stale_account, now=T0,
        )
        self.assertEqual(stale_snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(stale_snapshot.audit_entry.triggered_rules, (ComplianceRuleId.ACCOUNT_STATE_STALE,))

        fresh_account = make_account_state(account_report_age_seconds=1.0)
        fresh_snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved_risk_r=1.0), make_portfolio_state(), fresh_account, now=T0,
        )
        self.assertEqual(fresh_snapshot.decision, ComplianceDecision.APPROVE)

    def test_stale_account_state_does_not_touch_position_management(self):
        """ComplianceEngine has no position-close/modify authority at all
        (ADR-028 Hard Rule 1 -- APPROVE/REDUCE/REJECT a proposed NEW
        entry only) -- portfolio_state's existing open_positions are
        passed through unchanged and never referenced by this gate."""
        from titan_protocol.risk_engine.models import OpenPosition, Direction

        existing_position = OpenPosition(pair="EURUSD", direction=Direction.LONG, size_r=1.0, opened_at=T0)
        engine = ComplianceEngine(make_config())
        account = make_account_state(account_report_age_seconds=999.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(positions=(existing_position,)), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)
        self.assertEqual(snapshot.audit_entry.triggered_rules, (ComplianceRuleId.ACCOUNT_STATE_STALE,))

    def test_configurable_threshold_via_profile_override(self):
        import dataclasses

        from titan_protocol.compliance_engine.config import ComplianceEngineConfig

        base_config = make_config()
        widened_profile = dataclasses.replace(
            base_config.profile_for("example_generic_profile"), max_account_state_age_seconds=120.0,
        )
        config = dataclasses.replace(base_config, rule_profiles=(widened_profile,))
        engine = ComplianceEngine(config)
        account = make_account_state(account_report_age_seconds=60.0)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(approved_risk_r=1.0), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.APPROVE)

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
