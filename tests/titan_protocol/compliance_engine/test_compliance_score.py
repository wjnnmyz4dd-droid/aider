"""Unit tests: the 0-100 Compliance Score (ADR-028 §5.11, Hard Rule 8)
-- informational only, never gates a decision."""

from __future__ import annotations

import unittest

from titan_protocol.compliance_engine.compliance_score import compute_compliance_score
from titan_protocol.compliance_engine.models import ComplianceLockState, ComplianceRuleProfile
from tests.titan_protocol.compliance_engine._fixtures import make_account_state, make_config


class TestComplianceScore(unittest.TestCase):
    def test_full_headroom_is_100(self):
        config = make_config()
        account = make_account_state(account_balance=100_000.0, daily_starting_balance=100_000.0, peak_balance=100_000.0, consecutive_losses=0)
        score = compute_compliance_score(account, ComplianceRuleProfile(), config)
        self.assertAlmostEqual(score, 100.0, places=6)

    def test_locked_is_zero(self):
        config = make_config()
        account = make_account_state(compliance_lock=ComplianceLockState(active=True, reason="x"))
        score = compute_compliance_score(account, ComplianceRuleProfile(), config)
        self.assertEqual(score, 0.0)

    def test_emergency_stop_is_zero(self):
        config = make_config()
        account = make_account_state(emergency_stop_active=True)
        score = compute_compliance_score(account, ComplianceRuleProfile(), config)
        self.assertEqual(score, 0.0)

    def test_partial_daily_loss_reduces_score(self):
        config = make_config()
        healthy = make_account_state(account_balance=100_000.0, daily_starting_balance=100_000.0, peak_balance=100_000.0)
        stressed = make_account_state(account_balance=97_000.0, daily_starting_balance=100_000.0, peak_balance=100_000.0)
        healthy_score = compute_compliance_score(healthy, ComplianceRuleProfile(), config)
        stressed_score = compute_compliance_score(stressed, ComplianceRuleProfile(), config)
        self.assertLess(stressed_score, healthy_score)

    def test_score_always_within_bounds(self):
        config = make_config()
        account = make_account_state(account_balance=0.0, daily_starting_balance=100_000.0, peak_balance=200_000.0, consecutive_losses=100)
        score = compute_compliance_score(account, ComplianceRuleProfile(), config)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_never_gates_a_decision_by_itself(self):
        # A very low score alone doesn't raise or reject -- it's purely
        # descriptive; verified simply by not raising for a zero-headroom account.
        config = make_config()
        account = make_account_state(account_balance=1.0, daily_starting_balance=100_000.0, peak_balance=200_000.0)
        score = compute_compliance_score(account, ComplianceRuleProfile(), config)
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
