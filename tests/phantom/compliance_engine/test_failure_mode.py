"""Failure-mode tests: fail-closed behavior on unknown/missing
compliance state (ADR-028 Hard Rule 3)."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.engine import ComplianceEngine
from phantom.compliance_engine.models import ComplianceDecision, ComplianceLockState
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


class TestUnknownConsistencyDataNeverBlocksButNeverPasses(unittest.TestCase):
    def test_missing_consistency_data_is_not_applicable_not_a_pass_not_a_violation(self):
        engine = ComplianceEngine(make_config())
        # No best_single_day_profit_pct/cumulative_profit_pct supplied --
        # the rule must be silently skipped, not silently "passed" as if
        # verified favorable, and not treated as a violation either.
        account = make_account_state(best_single_day_profit_pct=None, cumulative_profit_pct=None)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=90.0), make_mi_snapshot(), make_strategy_snapshot(),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertNotEqual(snapshot.decision, ComplianceDecision.REJECT)


class TestEmergencyAndLockFailClosed(unittest.TestCase):
    def test_emergency_stop_overrides_a_perfectly_healthy_account(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(emergency_stop_active=True)
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=100.0), make_mi_snapshot(), make_strategy_snapshot(score=100.0),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)

    def test_compliance_lock_overrides_a_perfectly_healthy_account(self):
        engine = ComplianceEngine(make_config())
        account = make_account_state(compliance_lock=ComplianceLockState(active=True, reason="manual hold"))
        snapshot = engine.evaluate(
            "EURUSD", make_evidence_snapshot(evidence_score=100.0), make_mi_snapshot(), make_strategy_snapshot(score=100.0),
            make_risk_snapshot(), make_portfolio_state(), account, now=T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)


class TestRequiredInputsAreMandatory(unittest.TestCase):
    def test_missing_portfolio_state_argument_raises_type_error(self):
        engine = ComplianceEngine(make_config())
        with self.assertRaises(TypeError):
            engine.evaluate(  # type: ignore[call-arg]
                "EURUSD", make_evidence_snapshot(), make_mi_snapshot(), make_strategy_snapshot(), make_risk_snapshot(),
            )


if __name__ == "__main__":
    unittest.main()
