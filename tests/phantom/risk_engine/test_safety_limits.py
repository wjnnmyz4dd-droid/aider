"""Portfolio tests: daily/weekly/monthly risk limit, portfolio heat
limit, correlation limit, max open positions, max positions per pair,
max currency exposure (ADR-027 §3)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.risk_engine.correlation import compute_correlation_status
from phantom.risk_engine.exposure import compute_exposure_summary
from phantom.risk_engine.models import RejectionReason
from phantom.risk_engine.safety_limits import check_safety_limits
from tests.phantom.risk_engine._fixtures import (
    T0,
    make_config,
    make_open_position,
    make_portfolio_state,
    make_trade_history,
    make_trade_result,
)


def _run(pair, candidate_risk_r, portfolio_state, trade_history, config):
    exposure = compute_exposure_summary(portfolio_state, ())
    correlation = compute_correlation_status(pair, portfolio_state, trade_history, config)
    return check_safety_limits(pair, candidate_risk_r, portfolio_state, trade_history, exposure, correlation, config, T0)


class TestUnknownPortfolioState(unittest.TestCase):
    def test_none_portfolio_state_never_rejects_but_warns(self):
        config = make_config()
        reason, warnings = _run("EURUSD", 1.0, None, None, config)
        self.assertIsNone(reason)
        self.assertTrue(any("unknown" in w.lower() for w in warnings))


class TestMaxOpenPositions(unittest.TestCase):
    def test_at_limit_rejects(self):
        config = make_config(max_open_positions=2)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD"), make_open_position(pair="AUDUSD")])
        reason, _ = _run("EURUSD", 0.1, portfolio, None, config)
        self.assertEqual(reason, RejectionReason.MAX_OPEN_POSITIONS_EXCEEDED)


class TestMaxPositionsPerPair(unittest.TestCase):
    def test_at_limit_for_same_pair_rejects(self):
        config = make_config(max_open_positions=10, max_positions_per_pair=1)
        portfolio = make_portfolio_state([make_open_position(pair="EURUSD")])
        reason, _ = _run("EURUSD", 0.1, portfolio, None, config)
        self.assertEqual(reason, RejectionReason.MAX_POSITIONS_PER_PAIR_EXCEEDED)


class TestMaxCurrencyExposure(unittest.TestCase):
    def test_exceeding_currency_cap_rejects(self):
        config = make_config(max_currency_exposure_r=1.0, max_open_positions=10, max_positions_per_pair=10)
        portfolio = make_portfolio_state([make_open_position(pair="EURGBP", size_r=0.9)])
        reason, _ = _run("EURUSD", 0.5, portfolio, None, config)
        self.assertEqual(reason, RejectionReason.MAX_CURRENCY_EXPOSURE_EXCEEDED)


class TestPortfolioHeat(unittest.TestCase):
    def test_exceeding_heat_limit_rejects(self):
        config = make_config(portfolio_heat_limit_r=1.0, max_concurrent_risk_r=1.0, max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0)
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD", size_r=0.9)])
        reason, _ = _run("EURUSD", 0.5, portfolio, None, config)
        self.assertEqual(reason, RejectionReason.PORTFOLIO_HEAT_EXCEEDED)


class TestCorrelationLimit(unittest.TestCase):
    def test_exceeding_correlated_risk_rejects(self):
        config = make_config(
            max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0,
            portfolio_heat_limit_r=100.0, max_concurrent_risk_r=100.0,
            high_correlation_threshold=0.5, max_correlated_risk_r=1.0,
        )
        portfolio = make_portfolio_state([make_open_position(pair="GBPUSD", size_r=0.9)])
        reason, _ = _run("EURUSD", 0.5, portfolio, None, config)
        self.assertEqual(reason, RejectionReason.CORRELATION_LIMIT_EXCEEDED)


class TestPeriodRiskLimits(unittest.TestCase):
    def test_daily_limit_exceeded_rejects(self):
        config = make_config(
            max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0,
            portfolio_heat_limit_r=100.0, max_concurrent_risk_r=100.0, max_correlated_risk_r=100.0,
            daily_risk_limit_r=1.0,
        )
        history = make_trade_history([make_trade_result(pair="EURUSD", risk_r=0.9, opened_at=T0 - timedelta(hours=1), closed_at=T0 - timedelta(minutes=30))])
        portfolio = make_portfolio_state([])
        reason, _ = _run("EURUSD", 0.5, portfolio, history, config)
        self.assertEqual(reason, RejectionReason.DAILY_RISK_LIMIT_EXCEEDED)

    def test_trade_outside_window_does_not_count(self):
        config = make_config(
            max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0,
            portfolio_heat_limit_r=100.0, max_concurrent_risk_r=100.0, max_correlated_risk_r=100.0,
            daily_risk_limit_r=1.0,
        )
        history = make_trade_history([make_trade_result(pair="EURUSD", risk_r=0.9, opened_at=T0 - timedelta(days=5), closed_at=T0 - timedelta(days=5))])
        portfolio = make_portfolio_state([])
        reason, _ = _run("EURUSD", 0.5, portfolio, history, config)
        self.assertIsNone(reason)

    def test_weekly_limit_exceeded_rejects(self):
        config = make_config(
            max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0,
            portfolio_heat_limit_r=100.0, max_concurrent_risk_r=100.0, max_correlated_risk_r=100.0,
            daily_risk_limit_r=100.0, weekly_risk_limit_r=1.0,
        )
        history = make_trade_history([make_trade_result(pair="EURUSD", risk_r=0.9, opened_at=T0 - timedelta(days=3), closed_at=T0 - timedelta(days=3))])
        portfolio = make_portfolio_state([])
        reason, _ = _run("EURUSD", 0.5, portfolio, history, config)
        self.assertEqual(reason, RejectionReason.WEEKLY_RISK_LIMIT_EXCEEDED)

    def test_monthly_limit_exceeded_rejects(self):
        config = make_config(
            max_open_positions=10, max_positions_per_pair=10, max_currency_exposure_r=100.0,
            portfolio_heat_limit_r=100.0, max_concurrent_risk_r=100.0, max_correlated_risk_r=100.0,
            daily_risk_limit_r=100.0, weekly_risk_limit_r=100.0, monthly_risk_limit_r=1.0,
        )
        history = make_trade_history([make_trade_result(pair="EURUSD", risk_r=0.9, opened_at=T0 - timedelta(days=20), closed_at=T0 - timedelta(days=20))])
        portfolio = make_portfolio_state([])
        reason, _ = _run("EURUSD", 0.5, portfolio, history, config)
        self.assertEqual(reason, RejectionReason.MONTHLY_RISK_LIMIT_EXCEEDED)


class TestWithinAllLimitsPasses(unittest.TestCase):
    def test_no_positions_no_history_always_passes(self):
        config = make_config()
        portfolio = make_portfolio_state([])
        reason, _ = _run("EURUSD", 0.1, portfolio, None, config)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
