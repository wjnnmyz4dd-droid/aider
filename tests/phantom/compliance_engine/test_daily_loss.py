"""Unit + boundary tests: the graduated Daily Loss Protection curve
(ADR-028 §5.1)."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.daily_loss import daily_loss_pct_consumed, evaluate_daily_loss_protection
from phantom.compliance_engine.models import ComplianceRuleProfile
from tests.phantom.compliance_engine._fixtures import make_account_state, make_config


class TestDailyLossPctConsumed(unittest.TestCase):
    def test_no_loss_is_zero(self):
        account = make_account_state(account_balance=100_000.0, daily_starting_balance=100_000.0)
        self.assertEqual(daily_loss_pct_consumed(account, ComplianceRuleProfile()), 0.0)

    def test_half_of_limit_consumed(self):
        # 2.5% equity loss against a 5% limit -> 50% of limit consumed
        account = make_account_state(account_balance=97_500.0, daily_starting_balance=100_000.0)
        self.assertAlmostEqual(daily_loss_pct_consumed(account, ComplianceRuleProfile()), 50.0, places=6)

    def test_profit_day_never_negative(self):
        account = make_account_state(account_balance=105_000.0, daily_starting_balance=100_000.0)
        self.assertEqual(daily_loss_pct_consumed(account, ComplianceRuleProfile()), 0.0)

    def test_zero_starting_balance_is_safe(self):
        account = make_account_state(account_balance=0.0, daily_starting_balance=0.0)
        self.assertEqual(daily_loss_pct_consumed(account, ComplianceRuleProfile()), 0.0)


class TestDailyLossBands(unittest.TestCase):
    def test_normal_band_no_reduction(self):
        config = make_config()
        account = make_account_state(account_balance=100_000.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config)
        self.assertEqual(evaluation.multiplier, 1.0)
        self.assertFalse(evaluation.hard_reject)

    def test_reduce_band(self):
        config = make_config()
        # 3% loss / 5% limit = 60% of limit -> 50-70% band
        account = make_account_state(account_balance=97_000.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config)
        self.assertLess(evaluation.multiplier, 1.0)
        self.assertFalse(evaluation.hard_reject)

    def test_elevated_band_requires_exceptional_evidence_score(self):
        config = make_config()
        # 3.75% loss / 5% limit = 75% -> 70-80% band, requires evidence >= 85
        account = make_account_state(account_balance=96_250.0, daily_starting_balance=100_000.0)
        passing = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config, evidence_score=90.0)
        self.assertFalse(passing.hard_reject)
        failing = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config, evidence_score=70.0)
        self.assertTrue(failing.hard_reject)
        self.assertEqual(failing.gate_kind, "evidence")

    def test_highest_quality_band_requires_strategy_score(self):
        config = make_config()
        # 4.25% loss / 5% limit = 85% -> 80-90% band, requires strategy score >= 90
        account = make_account_state(account_balance=95_750.0, daily_starting_balance=100_000.0)
        passing = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config, evidence_score=90.0, strategy_score=95.0)
        self.assertFalse(passing.hard_reject)
        failing = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config, evidence_score=90.0, strategy_score=50.0)
        self.assertTrue(failing.hard_reject)
        self.assertEqual(failing.gate_kind, "strategy")

    def test_final_band_always_hard_rejects(self):
        config = make_config()
        # 4.75% loss / 5% limit = 95% -> final band, no new trades
        account = make_account_state(account_balance=95_250.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_daily_loss_protection(account, ComplianceRuleProfile(), config, evidence_score=100.0, strategy_score=100.0)
        self.assertTrue(evaluation.hard_reject)
        self.assertIsNone(evaluation.gate_kind)  # a genuine band reject, not a confidence-gate failure

    def test_band_boundaries_never_overlap_or_gap(self):
        config = make_config()
        bands = sorted(config.daily_loss_bands, key=lambda b: b.min_pct)
        for i in range(len(bands) - 1):
            self.assertAlmostEqual(bands[i].max_pct, bands[i + 1].min_pct, places=6)


if __name__ == "__main__":
    unittest.main()
