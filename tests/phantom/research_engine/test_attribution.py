"""Attribution tests: the generic `attribute_by()`/`attribute_all_dimensions()`
grouping (ADR-029 §5) -- all 13 named dimensions, rejected-candidate
exclusion, and no-duplicate-calculation reuse of `risk_engine.statistics`."""

from __future__ import annotations

import unittest

from phantom.research_engine.attribution import DIMENSION_KEY_FUNCS, attribute_all_dimensions, attribute_by
from phantom.research_engine.models import AttributionDimension
from tests.phantom.research_engine._fixtures import make_config, make_executed_trade, make_rejected_trade


class TestAllThirteenDimensions(unittest.TestCase):
    def test_all_13_dimensions_present(self):
        self.assertEqual(len(DIMENSION_KEY_FUNCS), 13)
        self.assertEqual(set(DIMENSION_KEY_FUNCS.keys()), set(AttributionDimension))

    def test_attribute_all_dimensions_returns_one_per_dimension(self):
        config = make_config()
        trades = [make_executed_trade(index=i) for i in range(12)]
        attributions = attribute_all_dimensions(trades, config)
        self.assertEqual(len(attributions), 13)
        self.assertEqual({a.dimension for a in attributions}, set(AttributionDimension))


class TestPairDimension(unittest.TestCase):
    def test_groups_by_pair(self):
        config = make_config()
        trades = [make_executed_trade(index=i, pair="EURUSD") for i in range(5)]
        trades += [make_executed_trade(index=i, pair="GBPUSD") for i in range(5, 10)]
        buckets = attribute_by(trades, DIMENSION_KEY_FUNCS[AttributionDimension.PAIR], config)
        self.assertEqual({b.key for b in buckets}, {"EURUSD", "GBPUSD"})
        self.assertEqual(dict((b.key, b.sample_size) for b in buckets), {"EURUSD": 5, "GBPUSD": 5})


class TestRejectedTradesExcluded(unittest.TestCase):
    def test_rejected_candidates_never_appear_in_any_bucket(self):
        config = make_config()
        trades = [make_executed_trade(index=i) for i in range(5)]
        trades.append(make_rejected_trade(index=100))
        attributions = attribute_all_dimensions(trades, config)
        for attribution in attributions:
            total_sample = sum(b.sample_size for b in attribution.buckets)
            self.assertLessEqual(total_sample, 5)


class TestTotalRAndStatisticsReuse(unittest.TestCase):
    def test_total_r_matches_sum_of_r_multiples(self):
        config = make_config()
        trades = [make_executed_trade(index=i, won=(i % 2 == 0)) for i in range(6)]
        buckets = attribute_by(trades, DIMENSION_KEY_FUNCS[AttributionDimension.PAIR], config)
        expected_total = sum(t.r_multiple for t in trades)
        self.assertAlmostEqual(buckets[0].total_r, expected_total, places=6)

    def test_bucket_statistics_come_from_reused_risk_engine_function(self):
        # Sanity: the returned StatisticalMetrics type is risk_engine's own,
        # not a locally-redefined type (ADR-029 §0).
        from phantom.risk_engine.models import StatisticalMetrics

        config = make_config()
        trades = [make_executed_trade(index=i) for i in range(6)]
        buckets = attribute_by(trades, DIMENSION_KEY_FUNCS[AttributionDimension.PAIR], config)
        self.assertIsInstance(buckets[0].statistics, StatisticalMetrics)


class TestDimensionSpecificGrouping(unittest.TestCase):
    def test_liquidity_sweep_dimension(self):
        config = make_config()
        trades = [make_executed_trade(index=i, liquidity_sweep_occurred=True) for i in range(3)]
        trades += [make_executed_trade(index=i, liquidity_sweep_occurred=False) for i in range(3, 6)]
        buckets = attribute_by(trades, DIMENSION_KEY_FUNCS[AttributionDimension.LIQUIDITY_SWEEP], config)
        self.assertEqual({b.key for b in buckets}, {"SWEEP", "NO_SWEEP"})

    def test_day_of_week_derived_from_evaluated_at_not_a_stored_field(self):
        config = make_config()
        trade = make_executed_trade(index=0)
        self.assertNotIn("day_of_week", trade.__dataclass_fields__)
        buckets = attribute_by([trade], DIMENSION_KEY_FUNCS[AttributionDimension.DAY_OF_WEEK], config)
        self.assertEqual(buckets[0].key, trade.evaluated_at.strftime("%A"))


if __name__ == "__main__":
    unittest.main()
