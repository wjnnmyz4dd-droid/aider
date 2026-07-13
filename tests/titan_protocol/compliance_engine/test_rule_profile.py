"""Unit + FTMO-profile-style tests: the remaining configurable
rule-profile checks (ADR-028 §5.5, §5.9)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from titan_protocol.compliance_engine.models import ComplianceRuleProfile
from titan_protocol.compliance_engine.rule_profile import (
    check_consistency_rule,
    check_max_trades_per_day,
    check_pair_disabled,
    check_required_stop_loss,
    check_weekend_restriction,
    profit_target_status,
    trading_days_status,
)
from tests.titan_protocol.compliance_engine._fixtures import make_account_state, make_config, make_risk_snapshot


class TestPairDisabled(unittest.TestCase):
    def test_disabled_pair_flagged(self):
        config = make_config(disabled_pairs=("EURUSD",))
        self.assertTrue(check_pair_disabled("EURUSD", config))
        self.assertFalse(check_pair_disabled("GBPUSD", config))


class TestWeekendRestriction(unittest.TestCase):
    def test_allowed_profile_never_restricted(self):
        config = make_config()
        profile = ComplianceRuleProfile(weekend_holding_allowed=True)
        friday_night = datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc)
        self.assertFalse(check_weekend_restriction(friday_night, profile, config))

    def test_disallowed_profile_blocks_past_cutoff(self):
        config = make_config(weekend_cutoff_weekday=4, weekend_cutoff_hour=20)
        profile = ComplianceRuleProfile(weekend_holding_allowed=False)
        friday_night = datetime(2026, 7, 10, 21, 0, tzinfo=timezone.utc)  # Friday
        self.assertTrue(check_weekend_restriction(friday_night, profile, config))

    def test_disallowed_profile_allows_before_cutoff(self):
        config = make_config(weekend_cutoff_weekday=4, weekend_cutoff_hour=20)
        profile = ComplianceRuleProfile(weekend_holding_allowed=False)
        friday_morning = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)  # Friday
        self.assertFalse(check_weekend_restriction(friday_morning, profile, config))

    def test_saturday_always_blocked_when_disallowed(self):
        config = make_config(weekend_cutoff_weekday=4, weekend_cutoff_hour=20)
        profile = ComplianceRuleProfile(weekend_holding_allowed=False)
        saturday = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)
        self.assertTrue(check_weekend_restriction(saturday, profile, config))


class TestRequiredStopLoss(unittest.TestCase):
    def test_profile_disabled_never_violates(self):
        profile = ComplianceRuleProfile(required_stop_loss=False)
        risk = make_risk_snapshot(approved=False)
        self.assertFalse(check_required_stop_loss(risk, profile))

    def test_approved_risk_with_positive_size_satisfies(self):
        profile = ComplianceRuleProfile(required_stop_loss=True)
        risk = make_risk_snapshot(approved=True, approved_risk_r=1.0)
        self.assertFalse(check_required_stop_loss(risk, profile))

    def test_missing_sizing_violates(self):
        profile = ComplianceRuleProfile(required_stop_loss=True)
        risk = make_risk_snapshot(approved=False)
        self.assertTrue(check_required_stop_loss(risk, profile))


class TestMaxTradesPerDay(unittest.TestCase):
    def test_at_limit_violates(self):
        profile = ComplianceRuleProfile(max_trades_per_day=5)
        account = make_account_state(trades_today_count=5)
        self.assertTrue(check_max_trades_per_day(account, profile))

    def test_below_limit_ok(self):
        profile = ComplianceRuleProfile(max_trades_per_day=5)
        account = make_account_state(trades_today_count=4)
        self.assertFalse(check_max_trades_per_day(account, profile))


class TestConsistencyRule(unittest.TestCase):
    def test_no_data_is_not_a_violation(self):
        profile = ComplianceRuleProfile(consistency_max_single_day_share=0.3)
        account = make_account_state(best_single_day_profit_pct=None, cumulative_profit_pct=None)
        self.assertFalse(check_consistency_rule(account, profile))

    def test_share_within_limit_ok(self):
        profile = ComplianceRuleProfile(consistency_max_single_day_share=0.3)
        account = make_account_state(best_single_day_profit_pct=2.0, cumulative_profit_pct=10.0)
        self.assertFalse(check_consistency_rule(account, profile))

    def test_share_exceeding_limit_violates(self):
        profile = ComplianceRuleProfile(consistency_max_single_day_share=0.3)
        account = make_account_state(best_single_day_profit_pct=5.0, cumulative_profit_pct=10.0)
        self.assertTrue(check_consistency_rule(account, profile))


class TestInformationalOnlyChecks(unittest.TestCase):
    def test_trading_days_status_never_blocks_but_reports(self):
        profile = ComplianceRuleProfile(min_trading_days=4)
        account = make_account_state(trading_days_count=2)
        self.assertEqual(trading_days_status(account, profile), False)
        account_met = make_account_state(trading_days_count=4)
        self.assertEqual(trading_days_status(account_met, profile), True)

    def test_profit_target_status_never_blocks_but_reports(self):
        profile = ComplianceRuleProfile(profit_target_pct=10.0)
        account = make_account_state(cumulative_profit_pct=5.0)
        self.assertEqual(profit_target_status(account, profile), False)


if __name__ == "__main__":
    unittest.main()
