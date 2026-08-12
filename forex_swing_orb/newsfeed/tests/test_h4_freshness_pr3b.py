"""PR-3B (H4) — news CONTENT freshness, not download recency.

Invariant: A RECENT DOWNLOAD IS NOT PROOF OF RECENT NEWS CONTENT. The effective
calendar freshness is pinned to when the content VERSION was first seen (or a trusted
source_as_of), never advanced by re-fetching identical content; unchanged/stale
content ages out through the existing compliance freshness rule and BLOCKS. Coverage
remains an independent requirement. Deterministic; injected fetcher (no network).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import NewsLockoutConfig, ReasonCode
from forex_swing_orb.compliance.news import gate_news
from forex_swing_orb.newsfeed.acquire import CalendarAcquirer
from forex_swing_orb.newsfeed.config import CalendarConfig
from forex_swing_orb.newsfeed.contract import (AcquisitionError, RawCalendar, Reason,
                                               HEALTH_FRESHNESS_UNESTABLISHED)
from forex_swing_orb.newsfeed.http_provider import ForexFactoryCalendarProvider
from forex_swing_orb.newsfeed.provider import InjectableCalendarProvider
from forex_swing_orb.newsfeed.service import CalendarAcquisitionService

UTC = timezone.utc
T0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)          # a Friday
NEWS_CFG = NewsLockoutConfig()                            # max_age_sec=3600 (1h)


def _iso(dt):
    return serialize.iso_utc(dt)


def week_rows(anchor, *, high_offset_min=10, tag="NFP"):
    return [
        {"title": tag, "country": "USD", "impact": "High",
         "date": _iso(anchor + timedelta(minutes=high_offset_min)),
         "forecast": "170K", "previous": "200K"},
        {"title": "EUR Data", "country": "EUR", "impact": "Low",
         "date": _iso(anchor - timedelta(days=2))},
        {"title": "GBP Data", "country": "GBP", "impact": "Medium",
         "date": _iso(anchor + timedelta(days=1))},
    ]


def _cfg(tmp_path, **over):
    out = tmp_path / "news.json"
    base = dict(enabled=True, provider="forexfactory", output_file=str(out),
                health_file=str(tmp_path / "status.json"), refresh_sec=1800,
                max_source_age_sec=21600, max_clock_skew_sec=120, source_file=None,
                static_trusted=False, timeout_sec=12.0, retries=0, backoff_sec=0,
                coverage_grace_sec=0, max_response_bytes=5_000_000,
                lock_file=str(tmp_path / "acq.lock"), log_file=None)
    base.update(over)
    return CalendarConfig(**base), out


def _raw(rows, now, *, source_as_of=None):
    return RawCalendar(source_name="ff", source_identifier="ff.json", provider_version="v1",
                       fetched_at=now, events=tuple(rows), source_as_of=source_as_of,
                       trusted=True)


def _acquire(rows, now, cfg, *, previous=None, source_as_of=None):
    prov = InjectableCalendarProvider(lambda n: _raw(rows, now, source_as_of=source_as_of))
    return CalendarAcquirer(prov, cfg).refresh(now, previous=previous)


def _ff_service(tmp_path, rows_fn, clock, **cfgover):
    """A service whose fetched_at + now track a mutable clock dict {'t': dt}."""
    cfg, out = _cfg(tmp_path, **cfgover)
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, mb: json.dumps(rows_fn()), now_fn=lambda: clock["t"])
    svc = CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                     now_fn=lambda: clock["t"], sleep_fn=lambda s: None)
    return svc, out, cfg


def _news_stale(bundle, now):
    v = gate_news({"symbol": "EURUSD.FX"}, bundle, NEWS_CFG, now)
    return (not v.passed) and ReasonCode.NEWS_DATA_STALE in v.reason_codes


# --------------------------------------------------------------------------- #
# 1/§8 — a recent download never advances effective freshness for unchanged content
# --------------------------------------------------------------------------- #
def test_unchanged_content_does_not_advance_effective_freshness(tmp_path):
    cfg, _ = _cfg(tmp_path)
    rows = week_rows(T0)
    b1 = _acquire(rows, T0, cfg)
    b2 = _acquire(rows, T0 + timedelta(minutes=45), cfg, previous=b1)   # same content, later fetch
    assert b1["as_of"] == _iso(T0)
    assert b2["as_of"] == b1["as_of"]                      # freshness PINNED, not advanced
    assert b2["provenance"]["fetched_at"] == _iso(T0 + timedelta(minutes=45))  # fetch DID advance
    assert b2["as_of"] != b2["provenance"]["fetched_at"]   # fetch time is never freshness


def test_fetch_time_alone_is_never_freshness(tmp_path):
    cfg, _ = _cfg(tmp_path)
    rows = week_rows(T0)
    b1 = _acquire(rows, T0, cfg)
    # age of the content keeps INCREASING across repeat identical fetches (arithmetic)
    ages = []
    prev = b1
    for m in (30, 90, 240):
        now = T0 + timedelta(minutes=m)
        prev = _acquire(rows, now, cfg, previous=prev)
        ages.append((now - serialize.parse_iso(prev["as_of"])).total_seconds())
    assert ages == sorted(ages) and ages[0] > 0            # strictly ageing, never reset


# --------------------------------------------------------------------------- #
# 2/9/§34 — repeated unchanged / stale-CDN eventually BLOCKS via compliance
# --------------------------------------------------------------------------- #
def test_repeated_unchanged_current_week_eventually_blocks(tmp_path):
    cfg, _ = _cfg(tmp_path)
    rows = week_rows(T0)
    b = _acquire(rows, T0, cfg)
    # within the freshness lifetime -> not stale
    assert not _news_stale(b, T0 + timedelta(minutes=30))
    # re-fetch identical content hours later: still pinned to T0 -> compliance BLOCKS
    b_later = _acquire(rows, T0 + timedelta(hours=3), cfg, previous=b)
    assert _news_stale(b_later, T0 + timedelta(hours=3))
    assert b_later["provenance"]["coverage_verified"] is True   # coverage still holds...
    # ...yet current-week coverage did NOT keep it fresh (H4 core)


def test_stale_cdn_identical_content_across_days_blocks(tmp_path):
    # CDN serves the SAME Friday file repeatedly; coverage keeps covering 'now'.
    clock = {"t": T0}
    rows = week_rows(T0, high_offset_min=6 * 60)            # HIGH event well outside lockout
    svc, out, _ = _ff_service(tmp_path, lambda: rows, clock)
    assert svc.refresh_once(T0) is True
    first_as_of = json.loads(out.read_text())["as_of"]
    # keep re-fetching identical content for hours
    for h in (1, 2, 4):
        clock["t"] = T0 + timedelta(hours=h)
        svc.refresh_once(clock["t"])
    bundle = json.loads(out.read_text())
    assert bundle["as_of"] == first_as_of                  # never rejuvenated by re-fetch
    assert _news_stale(bundle, T0 + timedelta(hours=4))     # stale -> news gate BLOCKS


# --------------------------------------------------------------------------- #
# 5/20/§34 — restart does not rejuvenate unchanged content (durable lineage)
# --------------------------------------------------------------------------- #
def test_restart_does_not_rejuvenate_unchanged_content(tmp_path):
    clock = {"t": T0}
    rows = week_rows(T0, high_offset_min=6 * 60)
    svc1, out, cfg = _ff_service(tmp_path, lambda: rows, clock)
    assert svc1.refresh_once(T0) is True
    first_as_of = json.loads(out.read_text())["as_of"]
    # brand-new service instance (fresh in-memory state) over the SAME output file
    clock2 = {"t": T0 + timedelta(hours=3)}
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, mb: json.dumps(rows), now_fn=lambda: clock2["t"])
    svc2 = CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                      now_fn=lambda: clock2["t"], sleep_fn=lambda s: None)
    assert svc2._last_content_hash is None                 # nothing in memory
    svc2.refresh_once(clock2["t"])
    bundle = json.loads(out.read_text())
    assert bundle["as_of"] == first_as_of                  # lineage recovered from disk
    assert _news_stale(bundle, clock2["t"])                # still stale after restart


def test_content_first_seen_persisted_in_bundle(tmp_path):
    cfg, out = _cfg(tmp_path)
    b = _acquire(week_rows(T0), T0, cfg)
    assert b["provenance"]["content_first_seen"] == _iso(T0)
    assert b["provenance"]["freshness_basis"] == "content_first_seen"


# --------------------------------------------------------------------------- #
# 6/10 — changed VALID content establishes a NEW version/lineage
# --------------------------------------------------------------------------- #
def test_changed_valid_content_establishes_new_version(tmp_path):
    cfg, _ = _cfg(tmp_path)
    b1 = _acquire(week_rows(T0, tag="NFP"), T0, cfg)
    later = T0 + timedelta(minutes=45)
    b2 = _acquire(week_rows(T0, tag="CPI"), later, cfg, previous=b1)   # different schedule
    assert b2["provenance"]["content_changed"] is True
    assert b2["provenance"]["content_hash"] != b1["provenance"]["content_hash"]
    assert b2["as_of"] == _iso(later)                      # fresh lineage at first sight
    assert not _news_stale(b2, later)


# --------------------------------------------------------------------------- #
# 7/11/12 — malformed / empty new content cannot authorize; LKG untouched
# --------------------------------------------------------------------------- #
def test_changed_malformed_content_not_authoritative(tmp_path):
    clock = {"t": T0}
    good = week_rows(T0, high_offset_min=6 * 60)
    state = {"rows": good}
    svc, out, _ = _ff_service(tmp_path, lambda: state["rows"], clock)
    assert svc.refresh_once(T0) is True
    good_as_of = json.loads(out.read_text())["as_of"]
    state["rows"] = "<<not json>>"                          # malformed changed content
    clock["t"] = T0 + timedelta(minutes=30)
    # fetcher returns a str already; force malformed by returning non-list JSON
    svc.acquirer.provider._fetch_url = lambda url, timeout, mb: "{}"   # object, not list
    assert svc.refresh_once(clock["t"]) is False           # not authoritative
    assert json.loads(out.read_text())["as_of"] == good_as_of   # LKG preserved, not extended


def test_empty_response_fails_closed(tmp_path):
    cfg, _ = _cfg(tmp_path)
    with pytest.raises(AcquisitionError) as e:
        _acquire([], T0, cfg)
    assert e.value.reason == Reason.EMPTY_PAYLOAD


# --------------------------------------------------------------------------- #
# 13/§13 — coverage and freshness are BOTH required, independently
# --------------------------------------------------------------------------- #
def test_wrong_coverage_blocks_even_if_freshly_fetched(tmp_path):
    cfg, _ = _cfg(tmp_path)
    with pytest.raises(AcquisitionError) as e:
        _acquire(week_rows(T0 - timedelta(days=7)), T0, cfg)   # last week's file, fetched now
    assert e.value.reason == Reason.COVERAGE_INVALID


def test_current_coverage_plus_stale_content_blocks(tmp_path):
    cfg, _ = _cfg(tmp_path)
    rows = week_rows(T0)
    b = _acquire(rows, T0, cfg)
    late = T0 + timedelta(hours=2)
    b_late = _acquire(rows, late, cfg, previous=b)
    assert b_late["provenance"]["coverage_start"] <= _iso(late) <= b_late["provenance"]["coverage_end"]
    assert _news_stale(b_late, late)                       # coverage OK but content stale -> block


# --------------------------------------------------------------------------- #
# 14/15/16 — source timestamp validation (trusted-source path)
# --------------------------------------------------------------------------- #
def test_future_source_timestamp_blocks(tmp_path):
    cfg, _ = _cfg(tmp_path)
    with pytest.raises(AcquisitionError) as e:
        _acquire(week_rows(T0), T0, cfg, source_as_of=T0 + timedelta(hours=1))
    assert e.value.reason == Reason.FUTURE_SOURCE_TIME


def test_naive_source_timestamp_blocks(tmp_path):
    cfg, _ = _cfg(tmp_path)
    naive = datetime(2026, 8, 7, 12, 0, 0)                  # tz-naive
    with pytest.raises(AcquisitionError) as e:
        _acquire(week_rows(T0), T0, cfg, source_as_of=naive)
    assert e.value.reason == Reason.INVALID_TIMESTAMP


def test_trusted_source_as_of_is_its_own_lineage(tmp_path):
    cfg, _ = _cfg(tmp_path)
    src = T0 - timedelta(minutes=20)
    b = _acquire(week_rows(T0), T0, cfg, source_as_of=src)
    assert b["as_of"] == _iso(src)                         # source timestamp, not fetch time
    assert b["provenance"]["freshness_basis"] == "source_as_of"


# --------------------------------------------------------------------------- #
# 21 — clock rollback cannot make stale content look fresh
# --------------------------------------------------------------------------- #
def test_clock_rollback_fails_closed(tmp_path):
    cfg, _ = _cfg(tmp_path)
    rows = week_rows(T0)
    b = _acquire(rows, T0, cfg)                             # first_seen = T0
    back = T0 - timedelta(hours=3)
    b2 = _acquire(rows, back, cfg, previous=b)             # clock rolled back, same content
    assert b2["as_of"] == _iso(T0)                          # lineage NOT moved younger
    # as_of is 'in the future' relative to the rolled-back now -> gate fails closed
    v = gate_news({"symbol": "EURUSD.FX"}, b2, NEWS_CFG, back)
    assert not v.passed and ReasonCode.NEWS_DATA_STALE in v.reason_codes


# --------------------------------------------------------------------------- #
# 27/28 — deterministic news authority regression (fresh bundle)
# --------------------------------------------------------------------------- #
def test_verified_current_no_relevant_event_passes(tmp_path):
    cfg, _ = _cfg(tmp_path)
    # HIGH event is USD but far outside the lockout window; EURUSD candidate at T0
    b = _acquire(week_rows(T0, high_offset_min=6 * 60), T0, cfg)
    v = gate_news({"symbol": "EURUSD.FX"}, b, NEWS_CFG, T0)
    assert v.passed                                        # fresh + no in-window relevant HIGH


def test_relevant_high_impact_event_blocks(tmp_path):
    cfg, _ = _cfg(tmp_path)
    b = _acquire(week_rows(T0, high_offset_min=5), T0, cfg)   # USD HIGH 5 min ahead
    v = gate_news({"symbol": "EURUSD.FX"}, b, NEWS_CFG, T0)
    assert not v.passed and ReasonCode.INTERNAL_NEWS_LOCKOUT in v.reason_codes


def test_pair_relevance_independent_of_session(tmp_path):
    # a USD HIGH event blocks EURUSD (USD is the quote) regardless of any session —
    # gate_news keys off currency, never a session id.
    cfg, _ = _cfg(tmp_path)
    b = _acquire(week_rows(T0, high_offset_min=5), T0, cfg)
    for pair in ("EURUSD.FX", "USDJPY.FX"):
        v = gate_news({"symbol": pair}, b, NEWS_CFG, T0)
        assert not v.passed                                 # USD event relevant to both
    # a JPY-only event does NOT block EURUSD (no shared currency)
    bj = _acquire([{"title": "BOJ", "country": "JPY", "impact": "High",
                    "date": _iso(T0 + timedelta(minutes=5))},
                   {"title": "x", "country": "EUR", "impact": "Low",
                    "date": _iso(T0 - timedelta(days=1))}], T0, cfg)
    assert gate_news({"symbol": "EURUSD.FX"}, bj, NEWS_CFG, T0).passed
