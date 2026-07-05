"""Per-constraint unit tests (ADR-005 §6-§14, §18)."""

from __future__ import annotations

import unittest

from phantom_pipeline.risk_engine import constraints as c
from phantom_pipeline.risk_engine.config import RiskEngineConfig
from phantom_pipeline.scanner.models import Direction, VolatilityLabel
from phantom_pipeline.risk_engine.models import OpenPosition
from tests.phantom_pipeline.risk_engine._fixtures import make_account_state, observation_with_volatility


class TestPerTradeCeiling(unittest.TestCase):
    def test_returns_the_configured_ceiling(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=2.0)
        result = c.per_trade_ceiling(config)
        self.assertEqual(result.allowed_risk_percent, 2.0)


class TestDailyBudget(unittest.TestCase):
    def test_missing_account_state_is_zero(self):
        result = c.daily_budget(None, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_missing_daily_allocated_field_is_zero(self):
        account = make_account_state(daily_risk_allocated_pct=None)
        result = c.daily_budget(account, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_remaining_budget_is_ceiling_minus_allocated(self):
        config = RiskEngineConfig(max_daily_risk_percent=3.0)
        account = make_account_state(daily_risk_allocated_pct=1.0)
        result = c.daily_budget(account, config)
        self.assertEqual(result.allowed_risk_percent, 2.0)

    def test_exhausted_budget_never_goes_negative(self):
        config = RiskEngineConfig(max_daily_risk_percent=3.0)
        account = make_account_state(daily_risk_allocated_pct=10.0)
        result = c.daily_budget(account, config)
        self.assertEqual(result.allowed_risk_percent, 0.0)


class TestPortfolioHeat(unittest.TestCase):
    def test_missing_account_state_is_zero(self):
        result = c.portfolio_heat(None, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_heat_reduces_remaining_headroom(self):
        config = RiskEngineConfig(max_portfolio_heat_percent=5.0)
        account = make_account_state(
            open_positions=(OpenPosition("EURUSD", Direction.UP, 2.0, None),)
        )
        result = c.portfolio_heat(account, config)
        self.assertEqual(result.allowed_risk_percent, 3.0)

    def test_heat_at_or_above_limit_is_zero(self):
        config = RiskEngineConfig(max_portfolio_heat_percent=5.0)
        account = make_account_state(
            open_positions=(OpenPosition("EURUSD", Direction.UP, 6.0, None),)
        )
        result = c.portfolio_heat(account, config)
        self.assertEqual(result.allowed_risk_percent, 0.0)


class TestCurrencyExposure(unittest.TestCase):
    def test_missing_account_state_is_zero(self):
        result = c.currency_exposure(None, "EURUSD", RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_unparseable_symbol_is_uncalculable(self):
        account = make_account_state()
        result = c.currency_exposure(account, "NOT_A_PAIR", RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_flat_account_yields_full_ceiling(self):
        config = RiskEngineConfig(max_currency_exposure_percent=4.0)
        account = make_account_state(open_positions=())
        result = c.currency_exposure(account, "EURUSD", config)
        self.assertEqual(result.allowed_risk_percent, 4.0)

    def test_existing_exposure_reduces_headroom_on_the_tighter_leg(self):
        config = RiskEngineConfig(max_currency_exposure_percent=4.0)
        account = make_account_state(
            open_positions=(OpenPosition("EURGBP", Direction.UP, 3.0, None),)
        )
        # EURGBP exposes EUR by 3.0%; EURUSD shares the EUR leg.
        result = c.currency_exposure(account, "EURUSD", config)
        self.assertEqual(result.allowed_risk_percent, 1.0)

    def test_unparseable_open_position_symbol_makes_the_whole_calc_uncalculable(self):
        account = make_account_state(
            open_positions=(OpenPosition("WEIRD_SYMBOL_1", Direction.UP, 1.0, None),)
        )
        result = c.currency_exposure(account, "EURUSD", RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)


class TestCorrelationExposure(unittest.TestCase):
    def test_missing_account_state_is_zero(self):
        result = c.correlation_exposure(None, "EURUSD", RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_unconfigured_bucket_is_never_assumed_safe(self):
        account = make_account_state()
        config = RiskEngineConfig()  # no correlation_buckets configured
        result = c.correlation_exposure(account, "EURUSD", config)
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_below_max_positions_allows_full_ceiling(self):
        config = RiskEngineConfig(
            correlation_buckets={"EURUSD": "MAJORS", "GBPUSD": "MAJORS"},
            max_positions_per_correlation_bucket=2,
            max_risk_percent_per_trade=1.5,
        )
        account = make_account_state(
            open_positions=(OpenPosition("GBPUSD", Direction.UP, 1.0, None),)
        )
        result = c.correlation_exposure(account, "EURUSD", config)
        self.assertEqual(result.allowed_risk_percent, 1.5)

    def test_at_max_positions_is_zero(self):
        config = RiskEngineConfig(
            correlation_buckets={"EURUSD": "MAJORS", "GBPUSD": "MAJORS"},
            max_positions_per_correlation_bucket=1,
        )
        account = make_account_state(
            open_positions=(OpenPosition("GBPUSD", Direction.UP, 1.0, None),)
        )
        result = c.correlation_exposure(account, "EURUSD", config)
        self.assertEqual(result.allowed_risk_percent, 0.0)


class TestVolatilityAdjustment(unittest.TestCase):
    def test_normal_volatility_applies_no_reduction(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        observation = observation_with_volatility(VolatilityLabel.NORMAL)
        result = c.volatility_adjustment(observation, config)
        self.assertEqual(result.allowed_risk_percent, 1.0)

    def test_extreme_volatility_reduces_risk(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        observation = observation_with_volatility(VolatilityLabel.EXTREME)
        result = c.volatility_adjustment(observation, config)
        self.assertLess(result.allowed_risk_percent, 1.0)

    def test_unknown_volatility_fails_closed_to_zero(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        observation = observation_with_volatility(VolatilityLabel.UNKNOWN)
        result = c.volatility_adjustment(observation, config)
        self.assertEqual(result.allowed_risk_percent, 0.0)


class TestLossStreakAdjustment(unittest.TestCase):
    def test_missing_account_state_is_zero(self):
        result = c.loss_streak_adjustment(None, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_missing_consecutive_losses_field_is_zero(self):
        account = make_account_state(consecutive_losses=None)
        result = c.loss_streak_adjustment(account, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_no_losses_applies_no_reduction(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        account = make_account_state(consecutive_losses=0)
        result = c.loss_streak_adjustment(account, config)
        self.assertEqual(result.allowed_risk_percent, 1.0)

    def test_streak_reduces_risk(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        account = make_account_state(consecutive_losses=5)
        result = c.loss_streak_adjustment(account, config)
        self.assertEqual(result.allowed_risk_percent, 0.0)


class TestDrawdownScaling(unittest.TestCase):
    def test_missing_account_state_is_zero(self):
        result = c.drawdown_scaling(None, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_missing_drawdown_field_is_zero(self):
        account = make_account_state(daily_drawdown_pct=None)
        result = c.drawdown_scaling(account, RiskEngineConfig())
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_low_drawdown_applies_no_reduction(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        account = make_account_state(daily_drawdown_pct=0.5, total_drawdown_pct=0.5)
        result = c.drawdown_scaling(account, config)
        self.assertEqual(result.allowed_risk_percent, 1.0)

    def test_high_drawdown_scales_to_zero(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        account = make_account_state(daily_drawdown_pct=6.0, total_drawdown_pct=1.0)
        result = c.drawdown_scaling(account, config)
        self.assertEqual(result.allowed_risk_percent, 0.0)

    def test_uses_the_worse_of_daily_or_total_drawdown(self):
        config = RiskEngineConfig(max_risk_percent_per_trade=1.0)
        account = make_account_state(daily_drawdown_pct=0.1, total_drawdown_pct=6.0)
        result = c.drawdown_scaling(account, config)
        self.assertEqual(result.allowed_risk_percent, 0.0)


if __name__ == "__main__":
    unittest.main()
