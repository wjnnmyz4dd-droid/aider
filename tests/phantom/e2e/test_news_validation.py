"""Phase 3B news validation: exercises the Market Intelligence Engine's
*actual* news behavior (never modified -- MI Engine is frozen for Phase
3B) end to end through a real `MarketIntelligenceEngine`, and documents
-- rather than silently patches -- the gaps between this checklist's
aspirational categories and what the frozen engine actually implements.

Known Limitations (confirmed by reading `phantom/market_intelligence/`,
not inferred): the frozen Market Intelligence Engine has no concept of a
named external provider at all.
  - No "Trading Economics" / "Forex Factory" (or any other) provider
    field anywhere on `NewsEvent` -- there is exactly one boolean input,
    `news_feed_trusted`, passed to `MarketIntelligenceEngine.evaluate()`.
    "Provider disagreement" and "provider outage" therefore have no
    literal code path: there is only one feed, trusted or not.
  - "Unknown provider" / "untrusted feed" collapse to the same single
    boolean -- an untrusted feed fails closed (blackout, score=0.0,
    `PairNewsIntelligence.blackout_reason="news feed untrusted -- failing
    closed"`), regardless of why it's untrusted.
  - Blackout windows are purely time-window-based (pre/post minutes
    relative to an event, with an optional per-pair override) -- there
    is no session-specific blackout rule; the same window applies
    whichever session `now` falls in.
  - There is no "weekend event" `NewsCategory` -- weekend proximity is a
    `market_safety.py` concept (`MarketSafetyInputs`/
    `weekend_approaching_penalty`), entirely separate from news events.
  - "Unknown event classification" is `NewsCategory.OTHER` -- it exists,
    but carries no special handling; it is priority (blackout-triggering)
    only if independently labeled `NewsImpact.HIGH`.

These gaps are recorded here as documentation, per Phase 3B's own bug
policy (no feature additions to a frozen engine) -- they are scope gaps
against this checklist's aspirational categories, not defects against
ADR-025.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom.evidence_engine.config import EvidenceEngineConfig
from phantom.evidence_engine.engine import EvidenceEngine
from phantom.market_intelligence.config import MarketIntelligenceConfig
from phantom.market_intelligence.engine import MarketIntelligenceEngine
from phantom.market_intelligence.models import MarketSafetyInputs, NewsCategory, NewsEvent, NewsImpact, PegPolicyEventType
from phantom.market_intelligence.peg_policy import PegPolicyRegistry
from tests.phantom.e2e._fixtures import make_bars

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)


def _evidence_report(pair: str = "EURUSD"):
    return EvidenceEngine(EvidenceEngineConfig()).evaluate(pair, make_bars(count=20), T0)


class TestTrustedVsUntrustedFeed(unittest.TestCase):
    def test_trusted_feed_with_no_events_has_no_blackout(self):
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate(
            "EURUSD", _evidence_report(), (), 1.0, 1.0, MarketSafetyInputs(), T0, news_feed_trusted=True,
        )
        self.assertFalse(snapshot.pair_safety.news.blackout_active)

    def test_untrusted_feed_fails_closed_regardless_of_events(self):
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate(
            "EURUSD", _evidence_report(), (), 1.0, 1.0, MarketSafetyInputs(), T0, news_feed_trusted=False,
        )
        self.assertTrue(snapshot.pair_safety.news.blackout_active)
        self.assertEqual(snapshot.pair_safety.news.news_score, 0.0)
        self.assertIn("untrusted", snapshot.pair_safety.news.blackout_reason)

    def test_unknown_provider_and_untrusted_feed_are_the_same_single_code_path(self):
        """Documents the gap: there is no separate "unknown provider"
        state -- `news_feed_trusted=False` is the only untrusted path,
        whatever the caller's reason for distrusting the feed."""
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        untrusted_for_unknown_provider = engine.evaluate(
            "EURUSD", _evidence_report(), (), 1.0, 1.0, MarketSafetyInputs(), T0, news_feed_trusted=False,
        )
        untrusted_for_outage = engine.evaluate(
            "EURUSD", _evidence_report(), (), 1.0, 1.0, MarketSafetyInputs(), T0, news_feed_trusted=False,
        )
        self.assertEqual(untrusted_for_unknown_provider.pair_safety.news, untrusted_for_outage.pair_safety.news)


class TestPriorityEventBlackout(unittest.TestCase):
    def test_high_impact_event_triggers_pre_news_blackout(self):
        event = NewsEvent(
            event_id="E1", currency="USD", category=NewsCategory.NFP, impact=NewsImpact.HIGH,
            scheduled_at=T0 + timedelta(minutes=10), released=False,
        )
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate("EURUSD", _evidence_report(), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)

    def test_low_impact_non_central_bank_event_never_triggers_blackout(self):
        event = NewsEvent(
            event_id="E2", currency="USD", category=NewsCategory.RETAIL_SALES, impact=NewsImpact.LOW,
            scheduled_at=T0 + timedelta(minutes=10), released=False,
        )
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate("EURUSD", _evidence_report(), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertFalse(snapshot.pair_safety.news.blackout_active)

    def test_central_bank_category_triggers_blackout_even_at_medium_impact(self):
        event = NewsEvent(
            event_id="E3", currency="USD", category=NewsCategory.FOMC, impact=NewsImpact.MEDIUM,
            scheduled_at=T0 + timedelta(minutes=5), released=False,
        )
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate("EURUSD", _evidence_report(), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)

    def test_pair_only_reacts_to_events_in_its_own_two_currencies(self):
        event = NewsEvent(
            event_id="E4", currency="JPY", category=NewsCategory.BOJ, impact=NewsImpact.HIGH,
            scheduled_at=T0 + timedelta(minutes=5), released=False,
        )
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate("EURUSD", _evidence_report(), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertFalse(snapshot.pair_safety.news.blackout_active)


class TestPairSpecificBlackout(unittest.TestCase):
    def test_pair_specific_override_widens_the_pre_news_window(self):
        config = MarketIntelligenceConfig(pre_news_blackout_minutes=5.0, pair_specific_blackout_overrides_minutes=(("EURUSD", 60.0),))
        event = NewsEvent(
            event_id="E5", currency="USD", category=NewsCategory.NFP, impact=NewsImpact.HIGH,
            scheduled_at=T0 + timedelta(minutes=30), released=False,
        )
        engine = MarketIntelligenceEngine(config)
        eurusd_snapshot = engine.evaluate("EURUSD", _evidence_report("EURUSD"), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        gbpusd_snapshot = engine.evaluate("GBPUSD", _evidence_report("GBPUSD"), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertTrue(eurusd_snapshot.pair_safety.news.blackout_active)
        self.assertFalse(gbpusd_snapshot.pair_safety.news.blackout_active)


class TestUnknownEventClassification(unittest.TestCase):
    def test_other_category_at_low_impact_never_triggers_blackout(self):
        event = NewsEvent(
            event_id="E6", currency="USD", category=NewsCategory.OTHER, impact=NewsImpact.LOW,
            scheduled_at=T0 + timedelta(minutes=5), released=False,
        )
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate("EURUSD", _evidence_report(), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertFalse(snapshot.pair_safety.news.blackout_active)

    def test_other_category_at_high_impact_still_triggers_blackout(self):
        """"Unknown" (OTHER) is not exempt from the ordinary
        impact-based rule -- only its category carries no special
        weight of its own."""
        event = NewsEvent(
            event_id="E7", currency="USD", category=NewsCategory.OTHER, impact=NewsImpact.HIGH,
            scheduled_at=T0 + timedelta(minutes=5), released=False,
        )
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig())
        snapshot = engine.evaluate("EURUSD", _evidence_report(), (event,), 1.0, 1.0, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)


class TestPegAndCentralBankPolicyEvents(unittest.TestCase):
    def test_currency_peg_event_stays_active_until_explicitly_cleared(self):
        registry = PegPolicyRegistry()
        registry.activate("EURCHF", PegPolicyEventType.CURRENCY_PEG, "SNB floor", T0)
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig(), peg_policy_registry=registry)
        snapshot = engine.evaluate("EURCHF", _evidence_report("EURCHF"), (), 1.0, 1.0, MarketSafetyInputs(), T0 + timedelta(days=30))
        self.assertTrue(snapshot.pair_safety.peg_policy.active)
        self.assertEqual(snapshot.pair_safety.peg_policy.event_type, PegPolicyEventType.CURRENCY_PEG)

    def test_emergency_intervention_clears_only_via_explicit_clear_call(self):
        registry = PegPolicyRegistry()
        registry.activate("USDJPY", PegPolicyEventType.EMERGENCY_INTERVENTION, "BOJ intervention", T0)
        registry.clear("USDJPY", T0 + timedelta(hours=1))
        engine = MarketIntelligenceEngine(MarketIntelligenceConfig(), peg_policy_registry=registry)
        snapshot = engine.evaluate("USDJPY", _evidence_report("USDJPY"), (), 1.0, 1.0, MarketSafetyInputs(), T0 + timedelta(hours=2))
        self.assertFalse(snapshot.pair_safety.peg_policy.active)


if __name__ == "__main__":
    unittest.main()
