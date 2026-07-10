"""Unit tests for Pair Safety scoring, Trade Readiness scoring, and
explainability."""

from __future__ import annotations

import unittest

from phantom.market_intelligence.explainability import build_explanation
from phantom.market_intelligence.models import (
    LiquidityIntelligence,
    MarketSafetyStatus,
    PairNewsIntelligence,
    PegPolicyEventType,
    PegPolicyStatus,
    SessionIntelligence,
)
from phantom.evidence_engine.models import SessionName
from phantom.market_intelligence.scoring import build_pair_safety, build_trade_readiness
from tests.phantom.market_intelligence._fixtures import make_config


def _news(score=100.0, blackout=False, reason=None):
    return PairNewsIntelligence("EURUSD", (), (), (), score, blackout, reason)


def _liquidity(score=100.0):
    return LiquidityIntelligence(1.0, 1.0, False, score, "ok")


def _session(score=100.0, preferred=True):
    return SessionIntelligence(SessionName.LONDON_NEW_YORK_OVERLAP, score, preferred, "ok")


def _market_safety(score=100.0, closed=False, halted=False, maintenance=False):
    return MarketSafetyStatus(False, False, False, maintenance, halted, closed, score, "ok")


def _peg(active=False):
    return PegPolicyStatus(active=active, event_type=PegPolicyEventType.CURRENCY_PEG if active else None, reason="reason" if active else None)


class TestPairSafety(unittest.TestCase):
    def test_normal_case_is_weighted_sum(self):
        config = make_config()
        news, liquidity, session, market_safety, peg = _news(), _liquidity(), _session(), _market_safety(), _peg()
        result = build_pair_safety("EURUSD", news, liquidity, session, market_safety, peg, config)
        self.assertEqual(result.pair_safety_score, 100.0)

    def test_peg_policy_active_hard_zeroes_score(self):
        config = make_config()
        result = build_pair_safety("USDCHF", _news(), _liquidity(), _session(), _market_safety(), _peg(active=True), config)
        self.assertEqual(result.pair_safety_score, 0.0)

    def test_market_closed_hard_zeroes_score_even_with_perfect_other_factors(self):
        config = make_config()
        result = build_pair_safety(
            "EURUSD", _news(), _liquidity(), _session(), _market_safety(closed=True), _peg(), config
        )
        self.assertEqual(result.pair_safety_score, 0.0)

    def test_trading_halted_hard_zeroes_score(self):
        config = make_config()
        result = build_pair_safety(
            "EURUSD", _news(), _liquidity(), _session(), _market_safety(halted=True), _peg(), config
        )
        self.assertEqual(result.pair_safety_score, 0.0)

    def test_broker_maintenance_hard_zeroes_score(self):
        config = make_config()
        result = build_pair_safety(
            "EURUSD", _news(), _liquidity(), _session(), _market_safety(maintenance=True), _peg(), config
        )
        self.assertEqual(result.pair_safety_score, 0.0)

    def test_score_bounded_for_partial_factors(self):
        config = make_config()
        result = build_pair_safety("EURUSD", _news(score=30.0), _liquidity(score=50.0), _session(score=20.0), _market_safety(score=60.0), _peg(), config)
        self.assertTrue(0.0 <= result.pair_safety_score <= 100.0)


class TestTradeReadiness(unittest.TestCase):
    def test_normal_case_is_weighted_sum(self):
        config = make_config()
        pair_safety = build_pair_safety("EURUSD", _news(), _liquidity(), _session(), _market_safety(), _peg(), config)
        readiness = build_trade_readiness(pair_safety, config)
        self.assertEqual(readiness.readiness_score, 100.0)

    def test_peg_policy_hard_zeroes_readiness(self):
        config = make_config()
        pair_safety = build_pair_safety("USDCHF", _news(), _liquidity(), _session(), _market_safety(), _peg(active=True), config)
        readiness = build_trade_readiness(pair_safety, config)
        self.assertEqual(readiness.readiness_score, 0.0)
        self.assertTrue(any("peg" in r.lower() for r in readiness.reasons))

    def test_news_blackout_hard_zeroes_readiness(self):
        config = make_config()
        news = _news(score=50.0, blackout=True, reason="NFP HIGH")
        pair_safety = build_pair_safety("EURUSD", news, _liquidity(), _session(), _market_safety(), _peg(), config)
        readiness = build_trade_readiness(pair_safety, config)
        self.assertEqual(readiness.readiness_score, 0.0)

    def test_absolute_market_safety_blocker_hard_zeroes_readiness(self):
        config = make_config()
        pair_safety = build_pair_safety("EURUSD", _news(), _liquidity(), _session(), _market_safety(halted=True), _peg(), config)
        readiness = build_trade_readiness(pair_safety, config)
        self.assertEqual(readiness.readiness_score, 0.0)

    def test_readiness_score_bounded(self):
        config = make_config()
        pair_safety = build_pair_safety("EURUSD", _news(score=40.0), _liquidity(score=60.0), _session(score=30.0, preferred=False), _market_safety(score=80.0), _peg(), config)
        readiness = build_trade_readiness(pair_safety, config)
        self.assertTrue(0.0 <= readiness.readiness_score <= 100.0)


class TestExplainability(unittest.TestCase):
    def test_explanation_has_all_seven_fields_populated(self):
        config = make_config()
        pair_safety = build_pair_safety(
            "EURUSD", _news(score=40.0, blackout=True, reason="NFP HIGH"), _liquidity(score=60.0),
            _session(score=30.0, preferred=False), _market_safety(score=80.0), _peg(), config,
        )
        readiness = build_trade_readiness(pair_safety, config)
        explanation = build_explanation(pair_safety, readiness)
        self.assertTrue(explanation.why_score_changed)
        self.assertIsInstance(explanation.upcoming_events, tuple)
        self.assertIsInstance(explanation.current_restrictions, tuple)
        self.assertEqual(explanation.blackout_reason, "NFP HIGH")
        self.assertTrue(explanation.session_reason)
        self.assertTrue(explanation.liquidity_reason)
        self.assertTrue(explanation.trade_readiness_explanation)
        self.assertIn("advisory only", explanation.trade_readiness_explanation)

    def test_restrictions_list_peg_policy_when_active(self):
        config = make_config()
        pair_safety = build_pair_safety("USDCHF", _news(), _liquidity(), _session(), _market_safety(), _peg(active=True), config)
        readiness = build_trade_readiness(pair_safety, config)
        explanation = build_explanation(pair_safety, readiness)
        self.assertTrue(any("peg" in r.lower() for r in explanation.current_restrictions))


if __name__ == "__main__":
    unittest.main()
