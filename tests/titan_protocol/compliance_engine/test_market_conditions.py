"""Unit tests: session restriction and news/peg/market-safety checks
(ADR-028 §5.6-5.7) -- read only from `MarketIntelligenceSnapshot`/
`EvidenceSnapshot`, never a provider directly."""

from __future__ import annotations

import dataclasses
import unittest

from titan_protocol.compliance_engine.market_conditions import (
    check_market_safety,
    check_max_spread,
    check_news_blackout,
    check_peg_policy,
    check_session_restriction,
)
from titan_protocol.compliance_engine.models import ComplianceRuleId, ComplianceRuleProfile
from titan_protocol.evidence_engine.models import SessionName
from titan_protocol.market_intelligence.models import MarketSafetyStatus
from tests.titan_protocol.compliance_engine._fixtures import make_evidence_snapshot, make_mi_snapshot


class TestSessionRestriction(unittest.TestCase):
    def test_approved_session_passes(self):
        evidence = make_evidence_snapshot()  # default session is LONDON_NEW_YORK_OVERLAP
        profile = ComplianceRuleProfile()
        self.assertFalse(check_session_restriction(evidence, profile))

    def test_unapproved_session_flagged(self):
        profile = ComplianceRuleProfile(approved_sessions=(SessionName.LONDON,))
        evidence = make_evidence_snapshot()  # LONDON_NEW_YORK_OVERLAP, not in approved set
        self.assertTrue(check_session_restriction(evidence, profile))


class TestMarketSafety(unittest.TestCase):
    def test_all_clear_returns_none(self):
        mi = make_mi_snapshot()
        self.assertIsNone(check_market_safety(mi))

    def test_trading_halted_wins_over_everything(self):
        mi = make_mi_snapshot()
        halted_safety = MarketSafetyStatus(
            is_holiday=True, is_early_close=False, is_weekend_approaching=False,
            broker_maintenance=True, trading_halted=True, market_closed=True, safety_score=0.0, reason="test",
        )
        pair_safety = dataclasses.replace(mi.pair_safety, market_safety=halted_safety)
        mi2 = dataclasses.replace(mi, pair_safety=pair_safety)
        self.assertEqual(check_market_safety(mi2), ComplianceRuleId.TRADING_HALTED)

    def test_holiday_alone_flagged(self):
        mi = make_mi_snapshot()
        holiday_safety = MarketSafetyStatus(
            is_holiday=True, is_early_close=False, is_weekend_approaching=False,
            broker_maintenance=False, trading_halted=False, market_closed=False, safety_score=50.0, reason="test",
        )
        pair_safety = dataclasses.replace(mi.pair_safety, market_safety=holiday_safety)
        mi2 = dataclasses.replace(mi, pair_safety=pair_safety)
        self.assertEqual(check_market_safety(mi2), ComplianceRuleId.HOLIDAY)


class TestNewsBlackout(unittest.TestCase):
    def test_disabled_profile_never_blocks(self):
        mi = make_mi_snapshot()
        profile = ComplianceRuleProfile(news_restriction_enabled=False)
        self.assertFalse(check_news_blackout(mi, profile))

    def test_no_blackout_passes(self):
        mi = make_mi_snapshot()
        profile = ComplianceRuleProfile(news_restriction_enabled=True)
        self.assertFalse(check_news_blackout(mi, profile))


class TestSpread(unittest.TestCase):
    def test_spread_within_limit_passes(self):
        mi = make_mi_snapshot()
        profile = ComplianceRuleProfile(max_spread=3.0)
        self.assertFalse(check_max_spread(mi, profile))

    def test_spread_above_limit_flagged(self):
        mi = make_mi_snapshot()
        profile = ComplianceRuleProfile(max_spread=0.5)  # fixture spread is 1.0
        self.assertTrue(check_max_spread(mi, profile))


class TestPegPolicy(unittest.TestCase):
    def test_inactive_passes(self):
        mi = make_mi_snapshot()
        self.assertFalse(check_peg_policy(mi))


if __name__ == "__main__":
    unittest.main()
