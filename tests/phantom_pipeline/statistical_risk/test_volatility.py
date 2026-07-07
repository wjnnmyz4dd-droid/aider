from __future__ import annotations

import unittest

from phantom_pipeline.scanner.models import VolatilityLabel
from phantom_pipeline.statistical_risk import volatility
from phantom_pipeline.statistical_risk.config import StatisticalRiskConfig
from phantom_pipeline.statistical_risk.models import RiskRecommendation

from ._fixtures import make_bars


class TestTrueRanges(unittest.TestCase):
    def test_first_bar_uses_high_minus_low(self):
        bars = make_bars([1.1000])
        trs = volatility.true_ranges(bars)
        self.assertAlmostEqual(trs[0], 0.0020, places=6)


class TestWildersAtr(unittest.TestCase):
    def test_none_with_insufficient_bars(self):
        bars = make_bars([1.1000, 1.1010])
        config = StatisticalRiskConfig(atr_period=14)
        self.assertIsNone(volatility.wilders_atr(bars, config.atr_period))

    def test_computed_with_enough_bars(self):
        bars = make_bars([1.1000 + 0.0001 * i for i in range(20)])
        atr = volatility.wilders_atr(bars, 14)
        self.assertIsNotNone(atr)
        self.assertGreater(atr, 0.0)


class TestRealizedVolatility(unittest.TestCase):
    def test_none_with_fewer_than_three_bars(self):
        self.assertIsNone(volatility.realized_volatility(make_bars([1.1, 1.2])))

    def test_zero_for_flat_prices(self):
        bars = make_bars([1.1000] * 10)
        self.assertEqual(volatility.realized_volatility(bars), 0.0)


class TestClassifyLabel(unittest.TestCase):
    def setUp(self):
        self.config = StatisticalRiskConfig()

    def test_none_ratio_is_unknown(self):
        self.assertEqual(volatility.classify_label(None, self.config), VolatilityLabel.UNKNOWN)

    def test_extreme_ratio(self):
        self.assertEqual(volatility.classify_label(3.0, self.config), VolatilityLabel.EXTREME)

    def test_compressed_ratio(self):
        self.assertEqual(volatility.classify_label(0.5, self.config), VolatilityLabel.COMPRESSED)

    def test_normal_ratio(self):
        self.assertEqual(volatility.classify_label(1.0, self.config), VolatilityLabel.NORMAL)


class TestRecommendationForVolatility(unittest.TestCase):
    def test_extreme_means_skip(self):
        from phantom_pipeline.statistical_risk.models import VolatilityState

        extreme_state = VolatilityState(VolatilityLabel.EXTREME, 0.01, 0.01, 5.0)
        self.assertEqual(volatility.recommendation_for_volatility(extreme_state), RiskRecommendation.SKIP_HIGH_RISK)

    def test_unknown_means_reduce_25(self):
        from phantom_pipeline.statistical_risk.models import VolatilityState

        unknown_state = VolatilityState(VolatilityLabel.UNKNOWN, None, None, None)
        self.assertEqual(
            volatility.recommendation_for_volatility(unknown_state), RiskRecommendation.REDUCE_RISK_25
        )

    def test_normal_means_normal_risk(self):
        from phantom_pipeline.statistical_risk.models import VolatilityState

        normal_state = VolatilityState(VolatilityLabel.NORMAL, 0.001, 0.0001, 1.0)
        self.assertEqual(
            volatility.recommendation_for_volatility(normal_state), RiskRecommendation.NORMAL_RISK
        )


class TestBuildVolatilityState(unittest.TestCase):
    def test_insufficient_bars_yields_unknown_label(self):
        state = volatility.build_volatility_state(make_bars([1.1]))
        self.assertEqual(state.label, VolatilityLabel.UNKNOWN)
        self.assertIsNone(state.atr)


if __name__ == "__main__":
    unittest.main()
