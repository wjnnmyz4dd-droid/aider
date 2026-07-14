"""End-to-end proof that news_ingestion's normalized events reach the
real, unmodified `MarketIntelligenceEngine` correctly through
`adapter.to_market_intelligence_event()` -- pair-specific currency
filtering, blackout windows, and high-impact/central-bank handling are
all MI's own existing, frozen logic (ADR-025); these tests only confirm
the wire/adapter path reaches it unmodified, never re-implement or
re-assert MI's internal decisions from scratch (mirrors the discipline
`tests/titan_protocol/bridge/test_market_data_endpoint.py` already
established for the market-data seam)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs
from titan_protocol.news_ingestion.adapter import to_market_intelligence_event
from titan_protocol.news_ingestion.models import NewsEventStatus

from tests.titan_protocol.market_intelligence._fixtures import T0, make_bars, make_config, make_evidence_report
from ._fixtures import make_normalized_event


class TestPairSpecificCurrencyFiltering(unittest.TestCase):
    """ADR-025 Hard Rule 2 (unmodified): only events touching a pair's
    own base/quote currency affect that pair -- news_ingestion supplies
    events for many currencies at once; MI itself narrows them down."""

    def setUp(self):
        self.engine = MarketIntelligenceEngine(make_config())
        self.evidence = make_evidence_report("EURUSD", T0)

    def test_unrelated_currency_event_does_not_trigger_a_blackout_for_this_pair(self):
        jpy_event = to_market_intelligence_event(make_normalized_event(
            currency="JPY", impact="high", scheduled_time=T0,
        ))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (jpy_event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        self.assertFalse(snapshot.pair_safety.news.blackout_active)

    def test_base_currency_event_does_trigger_a_blackout_for_this_pair(self):
        eur_event = to_market_intelligence_event(make_normalized_event(
            currency="EUR", impact="high", scheduled_time=T0,
        ))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (eur_event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)

    def test_quote_currency_event_does_trigger_a_blackout_for_this_pair(self):
        usd_event = to_market_intelligence_event(make_normalized_event(
            currency="USD", impact="high", scheduled_time=T0,
        ))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (usd_event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)


class TestHighImpactAndCentralBankEvents(unittest.TestCase):
    def setUp(self):
        self.engine = MarketIntelligenceEngine(make_config())
        self.evidence = make_evidence_report("EURUSD", T0)

    def test_high_impact_event_within_blackout_window_blacks_out(self):
        event = to_market_intelligence_event(make_normalized_event(currency="USD", impact="high", scheduled_time=T0 + timedelta(minutes=10)))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)

    def test_low_impact_event_does_not_black_out(self):
        event = to_market_intelligence_event(make_normalized_event(currency="USD", impact="low", scheduled_time=T0 + timedelta(minutes=10)))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        self.assertFalse(snapshot.pair_safety.news.blackout_active)

    def test_central_bank_category_forces_blackout_even_if_provider_mislabels_impact_medium(self):
        event = to_market_intelligence_event(make_normalized_event(currency="USD", category="fomc", impact="medium", scheduled_time=T0 + timedelta(minutes=10)))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)

    def test_unmapped_category_and_impact_fail_safe_to_other_and_high(self):
        event = to_market_intelligence_event(make_normalized_event(currency="USD", category="some new indicator nobody mapped", impact="unknown-value", scheduled_time=T0 + timedelta(minutes=10)))
        snapshot = self.engine.evaluate("EURUSD", self.evidence, (event,), 0.0002, 0.0002, MarketSafetyInputs(), T0)
        # Unmapped impact fails safe to HIGH -- still blacks out, never silently treated as harmless.
        self.assertTrue(snapshot.pair_safety.news.blackout_active)


class TestUntrustedNewsFailsClosedThroughTheSameSeam(unittest.TestCase):
    def test_news_feed_trusted_false_forces_mi_blackout_regardless_of_events(self):
        engine = MarketIntelligenceEngine(make_config())
        evidence = make_evidence_report("EURUSD", T0)
        snapshot = engine.evaluate("EURUSD", evidence, (), 0.0002, 0.0002, MarketSafetyInputs(), T0, news_feed_trusted=False)
        self.assertTrue(snapshot.pair_safety.news.blackout_active)
        self.assertEqual(snapshot.pair_safety.news.news_score, 0.0)


class TestReleasedEventStatus(unittest.TestCase):
    def test_released_event_maps_released_true_with_released_at(self):
        event = to_market_intelligence_event(make_normalized_event(status=NewsEventStatus.RELEASED, actual=3.1))
        self.assertTrue(event.released)
        self.assertIsNotNone(event.released_at)

    def test_scheduled_event_maps_released_false_with_no_released_at(self):
        event = to_market_intelligence_event(make_normalized_event(status=NewsEventStatus.SCHEDULED))
        self.assertFalse(event.released)
        self.assertIsNone(event.released_at)


if __name__ == "__main__":
    unittest.main()
