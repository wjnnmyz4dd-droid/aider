"""Unit category (ADR-030 §5.9): Monte Carlo Validation, reusing
`risk_engine.monte_carlo.run_monte_carlo` directly."""

from __future__ import annotations

import unittest

from phantom.validation_engine.monte_carlo_validation import run_monte_carlo_validation
from tests.phantom.validation_engine._fixtures import make_config, make_repeating_executed_trades, make_trade_history


class TestMonteCarloValidation(unittest.TestCase):
    def test_returns_none_for_empty_history(self):
        config = make_config()
        result = run_monte_carlo_validation((), config)
        self.assertIsNone(result)

    def test_produces_drawdown_and_risk_of_ruin_for_sufficient_history(self):
        config = make_config()
        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        result = run_monte_carlo_validation(trades, config)
        self.assertIsNotNone(result)
        self.assertEqual(result.sample_size, 30)
        self.assertGreater(result.simulations_run, 0)
        self.assertIsNotNone(result.expected_drawdown)
        self.assertIsNotNone(result.risk_of_ruin)

    def test_excludes_rejected_trades(self):
        from tests.phantom.validation_engine._fixtures import make_rejected_trade

        trades = make_repeating_executed_trades(count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5)
        rejected = [make_rejected_trade(index=i + 100) for i in range(5)]
        result_without = run_monte_carlo_validation(trades, make_config())
        result_with = run_monte_carlo_validation(trades + rejected, make_config())
        self.assertEqual(result_without.sample_size, result_with.sample_size)


if __name__ == "__main__":
    unittest.main()
