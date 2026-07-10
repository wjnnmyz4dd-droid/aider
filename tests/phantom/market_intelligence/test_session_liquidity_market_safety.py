"""Unit tests for session intelligence, liquidity quality, and market
safety."""

from __future__ import annotations

import unittest
from datetime import date, time, timedelta

from phantom.evidence_engine.models import SessionName
from phantom.market_intelligence.liquidity_intelligence import evaluate_liquidity
from phantom.market_intelligence.market_safety import evaluate_market_safety
from phantom.market_intelligence.models import MarketSafetyInputs
from phantom.market_intelligence.session_intelligence import evaluate_session
from tests.phantom.market_intelligence._fixtures import T0, make_config


class TestSessionIntelligence(unittest.TestCase):
    def test_preferred_session_is_flagged(self):
        config = make_config()
        result = evaluate_session(T0, config)  # T0 = overlap hour
        self.assertTrue(result.preferred)
        self.assertEqual(result.session, SessionName.LONDON_NEW_YORK_OVERLAP)

    def test_asian_session_downweighted_when_not_enabled(self):
        config = make_config(asian_session_enabled=False)
        asian_time = T0.replace(hour=2)
        result = evaluate_session(asian_time, config)
        self.assertEqual(result.session, SessionName.ASIAN)
        self.assertFalse(result.preferred)
        self.assertLess(result.session_score, 40.0)  # below Evidence Engine's raw Asian quality

    def test_asian_session_not_downweighted_when_enabled(self):
        config = make_config(asian_session_enabled=True)
        asian_time = T0.replace(hour=2)
        result = evaluate_session(asian_time, config)
        self.assertEqual(result.session_score, 40.0)  # unpenalized raw quality

    def test_session_score_bounded(self):
        config = make_config()
        for hour in range(24):
            result = evaluate_session(T0.replace(hour=hour), config)
            self.assertTrue(0.0 <= result.session_score <= 100.0)


class TestLiquidityIntelligence(unittest.TestCase):
    def test_normal_spread_scores_100(self):
        config = make_config()
        result = evaluate_liquidity(1.0, 1.0, config)
        self.assertEqual(result.liquidity_score, 100.0)
        self.assertFalse(result.spread_widening)

    def test_widening_spread_flagged_and_scored_lower(self):
        config = make_config()
        result = evaluate_liquidity(2.0, 1.0, config)
        self.assertTrue(result.spread_widening)
        self.assertLess(result.liquidity_score, 100.0)

    def test_extreme_widening_floors_at_zero(self):
        config = make_config()
        result = evaluate_liquidity(100.0, 1.0, config)
        self.assertEqual(result.liquidity_score, 0.0)

    def test_zero_average_spread_does_not_raise(self):
        config = make_config()
        result = evaluate_liquidity(0.0, 0.0, config)
        self.assertTrue(0.0 <= result.liquidity_score <= 100.0)
        result2 = evaluate_liquidity(1.0, 0.0, config)
        self.assertEqual(result2.liquidity_score, 0.0)


class TestMarketSafety(unittest.TestCase):
    def test_no_concerns_scores_100(self):
        config = make_config()
        result = evaluate_market_safety(T0, MarketSafetyInputs(), config)
        self.assertEqual(result.safety_score, 100.0)

    def test_holiday_zeroes_score(self):
        config = make_config()
        inputs = MarketSafetyInputs(holidays=(T0.date(),))
        result = evaluate_market_safety(T0, inputs, config)
        self.assertTrue(result.is_holiday)
        self.assertEqual(result.safety_score, 0.0)

    def test_early_close_detected(self):
        config = make_config()
        inputs = MarketSafetyInputs(early_closes=((T0.date(), time(12, 0)),))
        result = evaluate_market_safety(T0, inputs, config)  # T0 is 13:00, after 12:00 close
        self.assertTrue(result.is_early_close)

    def test_no_early_close_before_close_time(self):
        config = make_config()
        inputs = MarketSafetyInputs(early_closes=((T0.date(), time(23, 0)),))
        result = evaluate_market_safety(T0, inputs, config)
        self.assertFalse(result.is_early_close)

    def test_weekend_approaching_friday_evening(self):
        config = make_config()
        result = evaluate_market_safety(T0.replace(hour=22), MarketSafetyInputs(), config)
        self.assertTrue(result.is_weekend_approaching)

    def test_not_weekend_approaching_friday_morning(self):
        config = make_config()
        result = evaluate_market_safety(T0.replace(hour=8), MarketSafetyInputs(), config)
        self.assertFalse(result.is_weekend_approaching)

    def test_saturday_is_weekend_approaching(self):
        config = make_config()
        saturday = T0 + timedelta(days=1)
        result = evaluate_market_safety(saturday, MarketSafetyInputs(), config)
        self.assertTrue(result.is_weekend_approaching)

    def test_broker_maintenance_zeroes_score(self):
        config = make_config()
        result = evaluate_market_safety(T0, MarketSafetyInputs(broker_maintenance_active=True), config)
        self.assertEqual(result.safety_score, 0.0)
        self.assertTrue(result.broker_maintenance)

    def test_trading_halted_zeroes_score(self):
        config = make_config()
        result = evaluate_market_safety(T0, MarketSafetyInputs(trading_halted=True), config)
        self.assertEqual(result.safety_score, 0.0)

    def test_market_closed_zeroes_score(self):
        config = make_config()
        result = evaluate_market_safety(T0, MarketSafetyInputs(market_closed=True), config)
        self.assertEqual(result.safety_score, 0.0)


if __name__ == "__main__":
    unittest.main()
