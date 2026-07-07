from __future__ import annotations

import unittest

from phantom_pipeline.statistical_risk import portfolio
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig
from phantom_pipeline.statistical_risk.models import RiskRecommendation

from ._fixtures import make_open_position


class TestPortfolioHeat(unittest.TestCase):
    def test_no_positions_is_zero(self):
        self.assertEqual(portfolio.portfolio_heat([]), 0.0)

    def test_sums_allocated_risk(self):
        positions = [
            make_open_position(symbol="EURUSD", allocated_risk_percent=1.0),
            make_open_position(symbol="GBPUSD", allocated_risk_percent=1.5),
        ]
        self.assertEqual(portfolio.portfolio_heat(positions), 2.5)


class TestRecommendationForPortfolioHeat(unittest.TestCase):
    def test_below_warning_is_normal(self):
        config = StatisticalRiskConfig(portfolio_heat_warning_pct=4.0)
        self.assertEqual(
            portfolio.recommendation_for_portfolio_heat(1.0, config), RiskRecommendation.NORMAL_RISK
        )

    def test_at_warning_is_reduce_25(self):
        config = StatisticalRiskConfig(portfolio_heat_warning_pct=4.0)
        self.assertEqual(
            portfolio.recommendation_for_portfolio_heat(4.0, config), RiskRecommendation.REDUCE_RISK_25
        )

    def test_double_warning_is_skip(self):
        config = StatisticalRiskConfig(portfolio_heat_warning_pct=4.0)
        self.assertEqual(
            portfolio.recommendation_for_portfolio_heat(8.0, config), RiskRecommendation.SKIP_HIGH_RISK
        )


class TestPositionConcentration(unittest.TestCase):
    def test_counts_by_symbol(self):
        positions = [
            make_open_position(symbol="EURUSD"),
            make_open_position(symbol="EURUSD"),
            make_open_position(symbol="GBPUSD"),
        ]
        self.assertEqual(portfolio.position_concentration(positions), {"EURUSD": 2, "GBPUSD": 1})


class TestCurrencyExposure(unittest.TestCase):
    def test_six_letter_fx_symbol_splits_into_base_and_quote(self):
        positions = [make_open_position(symbol="EURUSD", allocated_risk_percent=1.0)]
        exposure = portfolio.currency_exposure(positions)
        self.assertEqual(exposure, {"EUR": 1.0, "USD": 1.0})

    def test_non_fx_symbol_grouped_under_its_own_name(self):
        positions = [make_open_position(symbol="XAUUSD_SPOT_CFD", allocated_risk_percent=1.0)]
        exposure = portfolio.currency_exposure(positions)
        self.assertEqual(exposure, {"XAUUSD_SPOT_CFD": 1.0})

    def test_shared_currency_accumulates_across_positions(self):
        positions = [
            make_open_position(symbol="EURUSD", allocated_risk_percent=1.0),
            make_open_position(symbol="EURGBP", allocated_risk_percent=1.0),
        ]
        exposure = portfolio.currency_exposure(positions)
        self.assertEqual(exposure["EUR"], 2.0)


class TestRecommendationForCurrencyExposure(unittest.TestCase):
    def test_below_warning_is_normal(self):
        config = StatisticalRiskConfig(currency_exposure_warning_pct=3.0)
        self.assertEqual(
            portfolio.recommendation_for_currency_exposure({"EUR": 1.0}, config),
            RiskRecommendation.NORMAL_RISK,
        )

    def test_at_warning_is_reduce_25(self):
        config = StatisticalRiskConfig(currency_exposure_warning_pct=3.0)
        self.assertEqual(
            portfolio.recommendation_for_currency_exposure({"EUR": 3.0}, config),
            RiskRecommendation.REDUCE_RISK_25,
        )

    def test_double_warning_is_reduce_50(self):
        config = StatisticalRiskConfig(currency_exposure_warning_pct=3.0)
        self.assertEqual(
            portfolio.recommendation_for_currency_exposure({"EUR": 6.0}, config),
            RiskRecommendation.REDUCE_RISK_50,
        )


if __name__ == "__main__":
    unittest.main()
