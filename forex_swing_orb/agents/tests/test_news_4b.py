"""Phase 4B — News & Compliance live behavior (checks 25-38)."""

from __future__ import annotations

from datetime import timedelta

from forex_swing_orb.agents import Assessment
from forex_swing_orb.agents.contract import NewsRating, ReasonCode
from forex_swing_orb.agents.agents import NewsComplianceAgent
import phase4b_helpers as H


def _news(newsb, symbol="EURUSD.FX", now=None):
    return NewsComplianceAgent().evaluate(
        H.req(symbol=symbol), H.ctx(news=newsb), now or H.NOW)


def test_news_clear_calendar():
    res = _news(H.news_bundle(events=[]))
    assert res["assessment"] == Assessment.CLEAR
    assert ReasonCode.NEWS_CLEAR in res["reason_codes"]


def test_news_caution_window_medium():
    res = _news(H.news_bundle(events=[H.event(currency="USD", impact="MEDIUM",
                                              minutes_from_now=15)]))
    assert res["assessment"] == Assessment.CAUTION
    assert ReasonCode.NEWS_CAUTION_WINDOW in res["reason_codes"]


def test_news_high_impact_pre_event_block():
    res = _news(H.news_bundle(events=[H.event(currency="EUR", impact="HIGH",
                                              minutes_from_now=10)]))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_HIGH_IMPACT_BLOCK in res["reason_codes"]


def test_news_high_impact_post_event_block():
    res = _news(H.news_bundle(events=[H.event(currency="USD", impact="HIGH",
                                              minutes_from_now=-10)]))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_HIGH_IMPACT_BLOCK in res["reason_codes"]


def test_news_missing_bundle():
    res = _news(None)
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_DATA_UNAVAILABLE in res["reason_codes"]


def test_news_stale_bundle():
    res = _news(H.news_bundle(events=[], age_sec=99999, max_age_sec=3600))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_DATA_STALE in res["reason_codes"]


def test_news_malformed_event():
    bad = {"currency": "EUR", "impact": "HIGH"}      # missing time/name/source/ingest
    res = _news(H.news_bundle(events=[bad]))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_DATA_MALFORMED in res["reason_codes"]


def test_news_unverifiable_source_bundle():
    res = _news(H.news_bundle(events=[], verified=False))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_SOURCE_UNVERIFIED in res["reason_codes"]


def test_news_unverifiable_event_state():
    ev = H.event(currency="EUR", impact="HIGH", minutes_from_now=10,
                 verification_state="RUMOR")
    res = _news(H.news_bundle(events=[ev]))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_SOURCE_UNVERIFIED in res["reason_codes"]


def test_news_timezone_ambiguity():
    # naive event timestamp with no timezone field -> ambiguous -> fail closed
    ev = H.event(currency="EUR", impact="HIGH",
                 event_timestamp="2024-01-25T12:10:00")   # no Z / offset
    res = _news(H.news_bundle(events=[ev]))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_TIMEZONE_AMBIGUOUS in res["reason_codes"]


def test_news_currency_mapping_relevance():
    # EUR event is relevant to EURUSD; a JPY event is not
    eur = H.event(currency="EUR", impact="HIGH", minutes_from_now=10)
    jpy = H.event(currency="JPY", impact="HIGH", minutes_from_now=10, name="BOJ")
    assert _news(H.news_bundle(events=[eur]))["assessment"] == Assessment.BLOCK
    assert _news(H.news_bundle(events=[jpy]))["assessment"] == Assessment.CLEAR


def test_news_currency_not_mapped():
    ev = H.event(currency="XYZ", impact="HIGH", minutes_from_now=10)
    res = _news(H.news_bundle(events=[ev]))
    assert ReasonCode.NEWS_CURRENCY_NOT_MAPPED in res["reason_codes"]


def test_news_conflicting_records():
    a = H.event(currency="EUR", impact="HIGH", minutes_from_now=10, event_id="dup-1")
    b = H.event(currency="EUR", impact="LOW", minutes_from_now=10, event_id="dup-1",
                event_timestamp=H.iso(H.NOW + timedelta(minutes=45)))
    res = _news(H.news_bundle(events=[a, b]))
    assert res["assessment"] == Assessment.BLOCK
    assert ReasonCode.NEWS_CONFLICTING_RECORDS in res["reason_codes"]


def test_news_weekend_context_processes():
    # a Saturday evaluation still processes events (operates 24/7)
    from datetime import datetime, timezone
    sat = datetime(2024, 1, 27, 12, 0, tzinfo=timezone.utc)   # Saturday
    ev = {"event_id": "wk", "source": "calendar",
          "source_timestamp": H.iso(sat), "event_timestamp": H.iso(sat),
          "currency": "USD", "impact": "LOW", "event_name": "x",
          "verification_state": "VERIFIED", "ingestion_timestamp": H.iso(sat)}
    nb = H.news_bundle(events=[ev]); nb["timestamp"] = H.iso(sat)
    res = _news(nb, now=sat)
    assert res["assessment"] == Assessment.CLEAR
    assert res["evidence"]["operates_24_7"] is True


def test_news_never_generates_direction():
    res = _news(H.news_bundle(events=[]))
    assert res["evidence"]["creates_direction"] is False
    for f in ("direction", "entry_price", "stop_loss", "take_profit"):
        assert f not in res


def test_news_deterministic_output():
    a = _news(H.news_bundle(events=[H.event(currency="EUR", impact="HIGH")]))
    b = _news(H.news_bundle(events=[H.event(currency="EUR", impact="HIGH")]))
    a.pop("generated_timestamp"); b.pop("generated_timestamp")
    assert a == b
