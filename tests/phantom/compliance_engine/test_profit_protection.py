"""Unit tests: Daily Profit Protection (ADR-028 §5.3) -- optional,
enabled by default; reduces risk and can optionally stop new positions."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.profit_protection import daily_profit_pct, evaluate_profit_protection
from tests.phantom.compliance_engine._fixtures import make_account_state, make_config


class TestDailyProfitPct(unittest.TestCase):
    def test_no_profit_is_zero(self):
        account = make_account_state(account_balance=100_000.0, daily_starting_balance=100_000.0)
        self.assertEqual(daily_profit_pct(account), 0.0)

    def test_loss_day_never_negative(self):
        account = make_account_state(account_balance=95_000.0, daily_starting_balance=100_000.0)
        self.assertEqual(daily_profit_pct(account), 0.0)

    def test_profit_pct_computed(self):
        account = make_account_state(account_balance=103_000.0, daily_starting_balance=100_000.0)
        self.assertAlmostEqual(daily_profit_pct(account), 3.0, places=6)


class TestProfitProtectionBands(unittest.TestCase):
    def test_disabled_returns_none(self):
        config = make_config(profit_protection_enabled=False)
        account = make_account_state(account_balance=105_000.0, daily_starting_balance=100_000.0)
        self.assertIsNone(evaluate_profit_protection(account, config))

    def test_normal_band_no_reduction(self):
        config = make_config()
        account = make_account_state(account_balance=100_500.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_profit_protection(account, config)
        self.assertEqual(evaluation.multiplier, 1.0)

    def test_reduces_past_2_pct(self):
        config = make_config()
        account = make_account_state(account_balance=102_500.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_profit_protection(account, config)
        self.assertLess(evaluation.multiplier, 1.0)
        self.assertFalse(evaluation.hard_reject)

    def test_stop_at_pct_triggers_hard_reject(self):
        config = make_config(profit_protection_stop_at_pct=4.0)
        account = make_account_state(account_balance=104_500.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_profit_protection(account, config)
        self.assertTrue(evaluation.hard_reject)

    def test_no_stop_configured_never_hard_rejects(self):
        config = make_config(profit_protection_stop_at_pct=None)
        account = make_account_state(account_balance=110_000.0, daily_starting_balance=100_000.0)
        evaluation = evaluate_profit_protection(account, config)
        self.assertFalse(evaluation.hard_reject)


if __name__ == "__main__":
    unittest.main()
