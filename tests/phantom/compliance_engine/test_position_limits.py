"""Portfolio tests: position/exposure limits (ADR-028 §5.8), reusing
`phantom.risk_engine.exposure`'s pure functions rather than a second
implementation."""

from __future__ import annotations

import unittest

from phantom.compliance_engine.models import ComplianceRuleId, ComplianceRuleProfile
from phantom.compliance_engine.position_limits import check_position_limits
from tests.phantom.compliance_engine._fixtures import make_account_state, make_open_position, make_portfolio_state


class TestPositionLimits(unittest.TestCase):
    def test_within_all_limits_passes(self):
        profile = ComplianceRuleProfile()
        portfolio = make_portfolio_state([])
        account = make_account_state()
        violation, exposure = check_position_limits("EURUSD", 1.0, portfolio, account, profile)
        self.assertIsNone(violation)

    def test_max_open_positions(self):
        profile = ComplianceRuleProfile(max_open_positions=1)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD")])
        account = make_account_state()
        violation, _ = check_position_limits("EURUSD", 1.0, portfolio, account, profile)
        self.assertEqual(violation, ComplianceRuleId.MAX_OPEN_POSITIONS_EXCEEDED)

    def test_max_positions_per_pair(self):
        profile = ComplianceRuleProfile(max_open_positions=10, max_positions_per_pair=1)
        portfolio = make_portfolio_state([make_open_position(pair="EURUSD")])
        account = make_account_state()
        violation, _ = check_position_limits("EURUSD", 1.0, portfolio, account, profile)
        self.assertEqual(violation, ComplianceRuleId.MAX_POSITIONS_PER_PAIR_EXCEEDED)

    def test_max_currency_exposure(self):
        profile = ComplianceRuleProfile(max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=1.0)
        portfolio = make_portfolio_state([make_open_position(pair="EURGBP", size_r=0.9)])
        account = make_account_state()
        violation, _ = check_position_limits("EURUSD", 0.5, portfolio, account, profile)
        self.assertEqual(violation, ComplianceRuleId.MAX_CURRENCY_EXPOSURE_EXCEEDED)

    def test_max_symbol_exposure(self):
        profile = ComplianceRuleProfile(max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0, max_symbol_exposure_r=1.0)
        portfolio = make_portfolio_state([make_open_position(pair="EURUSD", size_r=0.9)])
        account = make_account_state()
        violation, _ = check_position_limits("EURUSD", 0.5, portfolio, account, profile)
        self.assertEqual(violation, ComplianceRuleId.MAX_SYMBOL_EXPOSURE_EXCEEDED)

    def test_max_pending_orders(self):
        profile = ComplianceRuleProfile(max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0, max_symbol_exposure_r=100.0, max_pending_orders=2)
        portfolio = make_portfolio_state([])
        account = make_account_state(pending_orders_count=2)
        violation, _ = check_position_limits("EURUSD", 0.5, portfolio, account, profile)
        self.assertEqual(violation, ComplianceRuleId.MAX_PENDING_ORDERS_EXCEEDED)

    def test_max_simultaneous_risk(self):
        profile = ComplianceRuleProfile(
            max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0,
            max_symbol_exposure_r=100.0, max_pending_orders=100, max_simultaneous_risk_r=1.0,
        )
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD", size_r=0.9)])
        account = make_account_state()
        violation, _ = check_position_limits("EURUSD", 0.5, portfolio, account, profile)
        self.assertEqual(violation, ComplianceRuleId.MAX_SIMULTANEOUS_RISK_EXCEEDED)


if __name__ == "__main__":
    unittest.main()
