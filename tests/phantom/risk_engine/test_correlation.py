"""Correlation tests: same-currency heuristic (sign-aware), measured
rolling correlation from `TradeHistory`, clusters, highly/negatively
correlated positions, cross-currency exposure, unknown-state fail-closed."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.risk_engine.correlation import compute_correlation_status, estimate_pair_correlation
from phantom.risk_engine.models import DataQuality
from tests.phantom.risk_engine._fixtures import (
    T0,
    make_config,
    make_open_position,
    make_portfolio_state,
    make_repeating_trade_history,
    make_trade_history,
    make_trade_result,
)


class TestStaticEstimate(unittest.TestCase):
    def test_same_side_shared_currency_is_positive(self):
        config = make_config()
        self.assertGreater(estimate_pair_correlation("EURUSD", "GBPUSD", None, config), 0.0)

    def test_opposite_side_shared_currency_is_negative(self):
        config = make_config()
        self.assertLess(estimate_pair_correlation("EURUSD", "USDCHF", None, config), 0.0)

    def test_no_shared_currency_is_zero(self):
        config = make_config()
        self.assertEqual(estimate_pair_correlation("EURUSD", "AUDNZD", None, config), 0.0)

    def test_same_pair_is_one(self):
        config = make_config()
        self.assertEqual(estimate_pair_correlation("EURUSD", "EURUSD", None, config), 1.0)

    def test_deterministic_across_repeated_calls(self):
        config = make_config()
        first = estimate_pair_correlation("EURUSD", "USDCHF", None, config)
        for _ in range(20):
            self.assertEqual(estimate_pair_correlation("EURUSD", "USDCHF", None, config), first)


class TestMeasuredRollingCorrelation(unittest.TestCase):
    def test_sufficient_samples_uses_measured_correlation_not_static(self):
        config = make_config(min_samples_for_rolling_correlation=10, rolling_correlation_window=20)
        results = []
        for i in range(15):
            r = 1.0 if i % 2 == 0 else -1.0
            results.append(make_trade_result(pair="EURUSD", r_multiple=r, opened_at=T0 + timedelta(days=i), closed_at=T0 + timedelta(days=i)))
            results.append(make_trade_result(pair="GBPUSD", r_multiple=r, opened_at=T0 + timedelta(days=i), closed_at=T0 + timedelta(days=i)))
        history = make_trade_history(results)
        # Perfectly co-moving synthetic series -- measured correlation should be ~1.0
        coeff = estimate_pair_correlation("EURUSD", "GBPUSD", history, config)
        self.assertAlmostEqual(coeff, 1.0, places=6)

    def test_insufficient_samples_falls_back_to_static(self):
        config = make_config(min_samples_for_rolling_correlation=50)
        history = make_repeating_trade_history(pair="EURUSD", count=5)
        coeff = estimate_pair_correlation("EURUSD", "GBPUSD", history, config)
        self.assertEqual(coeff, config.shared_currency_correlation_estimate)


class TestCorrelationStatus(unittest.TestCase):
    def test_unknown_portfolio_state_fails_closed(self):
        config = make_config()
        status = compute_correlation_status("EURUSD", None, None, config)
        self.assertEqual(status.data_quality, DataQuality.UNKNOWN)
        self.assertFalse(status.limit_exceeded)

    def test_highly_correlated_pair_flagged(self):
        config = make_config(high_correlation_threshold=0.5)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD", size_r=1.0)])
        status = compute_correlation_status("EURUSD", portfolio, None, config)
        self.assertIn("GBPUSD", status.highly_correlated_pairs)

    def test_negatively_correlated_pair_flagged(self):
        config = make_config(negative_correlation_threshold=-0.5)
        portfolio = make_portfolio_state([make_open_position(pair="USDCHF", size_r=1.0)])
        status = compute_correlation_status("EURUSD", portfolio, None, config)
        self.assertIn("USDCHF", status.negatively_correlated_pairs)

    def test_cross_currency_exposure_sums_shared_currency_positions(self):
        config = make_config()
        portfolio = make_portfolio_state([
            make_open_position(pair="GBPUSD", size_r=1.0),
            make_open_position(pair="USDCHF", size_r=0.5),
            make_open_position(pair="AUDNZD", size_r=2.0),
        ])
        status = compute_correlation_status("EURUSD", portfolio, None, config)
        self.assertAlmostEqual(status.cross_currency_exposure_r, 1.5)

    def test_correlation_limit_exceeded_flagged(self):
        config = make_config(high_correlation_threshold=0.5, max_correlated_risk_r=0.5)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD", size_r=1.0)])
        status = compute_correlation_status("EURUSD", portfolio, None, config)
        self.assertTrue(status.limit_exceeded)

    def test_clusters_include_every_open_pair_and_the_candidate(self):
        config = make_config(high_correlation_threshold=0.5)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD", size_r=1.0)])
        status = compute_correlation_status("EURUSD", portfolio, None, config)
        clustered_pairs = {p for cluster in status.correlation_clusters for p in cluster}
        self.assertEqual(clustered_pairs, {"EURUSD", "GBPUSD"})


if __name__ == "__main__":
    unittest.main()
