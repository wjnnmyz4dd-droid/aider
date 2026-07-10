"""Unit + boundary tests: Total Drawdown Protection (ADR-028 §5.2) --
never trades into the hard limit."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.drawdown import evaluate_drawdown_protection, total_drawdown_pct_consumed
from phantom.compliance_engine.models import ComplianceRuleProfile
from tests.phantom.compliance_engine._fixtures import make_account_state, make_config


class TestDrawdownPctConsumed(unittest.TestCase):
    def test_no_drawdown_is_zero(self):
        account = make_account_state(account_balance=100_000.0, peak_balance=100_000.0)
        self.assertEqual(total_drawdown_pct_consumed(account, ComplianceRuleProfile()), 0.0)

    def test_half_of_limit_consumed(self):
        # 5% drawdown / 10% limit = 50%
        account = make_account_state(account_balance=95_000.0, peak_balance=100_000.0)
        self.assertAlmostEqual(total_drawdown_pct_consumed(account, ComplianceRuleProfile()), 50.0, places=6)


class TestDrawdownBands(unittest.TestCase):
    def test_normal_band(self):
        config = make_config()
        account = make_account_state(account_balance=100_000.0, peak_balance=100_000.0)
        evaluation = evaluate_drawdown_protection(account, ComplianceRuleProfile(), config)
        self.assertEqual(evaluation.multiplier, 1.0)
        self.assertFalse(evaluation.hard_reject)

    def test_final_band_always_hard_rejects(self):
        config = make_config()
        # 9.5% drawdown / 10% limit = 95%
        account = make_account_state(account_balance=90_500.0, peak_balance=100_000.0)
        evaluation = evaluate_drawdown_protection(account, ComplianceRuleProfile(), config)
        self.assertTrue(evaluation.hard_reject)

    def test_never_trades_into_the_hard_limit(self):
        config = make_config()
        # exactly at the configured max_total_drawdown_pct
        account = make_account_state(account_balance=90_000.0, peak_balance=100_000.0)
        evaluation = evaluate_drawdown_protection(account, ComplianceRuleProfile(), config)
        self.assertTrue(evaluation.hard_reject)


if __name__ == "__main__":
    unittest.main()
