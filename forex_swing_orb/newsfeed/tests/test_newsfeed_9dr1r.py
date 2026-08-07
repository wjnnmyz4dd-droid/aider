"""Phase 9D-R1-R — freshness hardening & live-validation tests.

Deterministic; NO public-internet access except the ONE explicitly-gated live probe
(skipped unless SESSION_EDGE_CALENDAR_LIVE_PROBE=1). Covers the coverage/effective-
freshness model (F-2), response hardening (F-5), informational-conflict recording
(F-7), the operational health status (F-6), the single-instance lock (F-4), and the
two mandatory end-to-end proofs (§13).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import NewsLockoutConfig
from forex_swing_orb.compliance.news import gate_news
from forex_swing_orb.live.providers import FileNewsDataProvider
from forex_swing_orb.newsfeed import normalize
from forex_swing_orb.newsfeed.acquire import CalendarAcquirer
from forex_swing_orb.newsfeed.config import CalendarConfig
from forex_swing_orb.newsfeed.contract import (AcquisitionError, RawCalendar, Reason,
                                               HEALTH_HEALTHY, HEALTH_FRESHNESS_UNESTABLISHED,
                                               HEALTH_SERVICE_STALE)
from forex_swing_orb.newsfeed.health import derive_service_status
from forex_swing_orb.newsfeed.http_provider import (ForexFactoryCalendarProvider,
                                                    _check_url_secure)
from forex_swing_orb.newsfeed.provider import InjectableCalendarProvider
from forex_swing_orb.newsfeed.service import CalendarAcquisitionService
from forex_swing_orb.newsfeed.supervisor import LockHeld, SingleInstanceLock

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)     # a Friday


def _iso(dt):
    return serialize.iso_utc(dt)


def week_rows(anchor, *, high_offset_min=10):
    """ForexFactory-style rows spanning the week around ``anchor`` (UTC), with a HIGH
    USD event ``high_offset_min`` from the anchor and a spread of lower events."""
    return [
        {"title": "NFP", "country": "USD", "impact": "High",
         "date": _iso(anchor + timedelta(minutes=high_offset_min)),
         "forecast": "170K", "previous": "200K"},
        {"title": "Monday Data", "country": "EUR", "impact": "Low",
         "date": _iso(anchor - timedelta(days=2))},
        {"title": "Friday Data", "country": "GBP", "impact": "Medium",
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


def _ff_service(tmp_path, rows, *, now=NOW, **cfgover):
    cfg, out = _cfg(tmp_path, **cfgover)
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: json.dumps(rows), now_fn=lambda: now)
    svc = CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                     now_fn=lambda: now, sleep_fn=lambda s: None)
    return svc, out, cfg


def _raw(rows, **kw):
    kw.setdefault("fetched_at", NOW)
    return RawCalendar(source_name="ff", source_identifier="ff.json",
                       provider_version="v1", events=tuple(rows), trusted=True, **kw)


def _acq(rows, tmp_path, **cfgover):
    cfg, _ = _cfg(tmp_path, **cfgover)
    prov = InjectableCalendarProvider(lambda now: _raw(rows), trusted=True)
    return CalendarAcquirer(prov, cfg)


# --------------------------------------------------------------------------- #
# F-2: coverage / effective freshness
# --------------------------------------------------------------------------- #
def test_current_week_accepted_and_as_of_is_effective(tmp_path):
    acq = _acq(week_rows(NOW), tmp_path)
    b = acq.refresh(NOW)
    assert b["provenance"]["coverage_verified"] is True
    assert b["as_of"] == b["provenance"]["effective_calendar_as_of"]
    assert b["provenance"]["coverage_start"] <= _iso(NOW) <= b["provenance"]["coverage_end"]


def test_previous_week_calendar_fails_closed(tmp_path):
    acq = _acq(week_rows(NOW - timedelta(days=7)), tmp_path)
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(NOW)
    assert e.value.reason == Reason.COVERAGE_INVALID


def test_future_week_calendar_fails_closed(tmp_path):
    acq = _acq(week_rows(NOW + timedelta(days=7)), tmp_path)
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(NOW)
    assert e.value.reason == Reason.COVERAGE_INVALID


def test_stale_upstream_http200_not_stamped_fresh(tmp_path):
    """The core F-2 defect: a successful fetch of a previous-week (stale) calendar
    must NOT be re-stamped fresh — acquisition fails closed instead of writing."""
    svc, out, _ = _ff_service(tmp_path, week_rows(NOW - timedelta(days=7)))
    assert svc.refresh_once(NOW) is False
    assert not out.exists()                          # last-known-good untouched
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["status"] == HEALTH_FRESHNESS_UNESTABLISHED


def test_source_as_of_stale_fails_closed(tmp_path):
    prov = InjectableCalendarProvider(
        lambda now: _raw(week_rows(NOW), source_as_of=NOW - timedelta(hours=7)))
    cfg, _ = _cfg(tmp_path)
    with pytest.raises(AcquisitionError) as e:
        CalendarAcquirer(prov, cfg).refresh(NOW)
    assert e.value.reason == Reason.STALE_SOURCE


def test_source_as_of_absent_uses_coverage(tmp_path):
    b = _acq(week_rows(NOW), tmp_path).refresh(NOW)
    assert b["provenance"]["source_as_of"] is None
    assert b["provenance"]["coverage_verified"] is True


def test_content_hash_and_change_tracking(tmp_path):
    acq = _acq(week_rows(NOW), tmp_path)
    b1 = acq.refresh(NOW, previous_content_hash=None)
    h1 = b1["provenance"]["content_hash"]
    assert b1["provenance"]["content_changed"] is None       # first sight
    b2 = acq.refresh(NOW, previous_content_hash=h1)
    assert b2["provenance"]["content_changed"] is False      # unchanged, still current
    assert b2["provenance"]["content_hash"] == h1


def test_repeated_unchanged_current_week_stays_valid(tmp_path):
    """Unchanged content is NOT assumed stale: a legitimately-static current-week
    calendar keeps validating (coverage holds)."""
    svc, out, _ = _ff_service(tmp_path, week_rows(NOW))
    assert svc.refresh_once(NOW) is True
    assert svc.refresh_once(NOW) is True
    assert out.exists()


# --------------------------------------------------------------------------- #
# boundary cases: Sunday/Monday, year boundary, DST
# --------------------------------------------------------------------------- #
def test_sunday_monday_boundary_current_week_ok(tmp_path):
    monday = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc)   # Monday
    b = _acq(week_rows(monday), tmp_path).refresh(monday)
    assert b["provenance"]["coverage_verified"] is True


def test_year_boundary_current_week_ok(tmp_path):
    nye = datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)
    b = _acq(week_rows(nye), tmp_path).refresh(nye)
    assert b["provenance"]["coverage_verified"] is True


def test_dst_offset_timestamps_parse_to_utc(tmp_path):
    rows = [{"title": "NFP", "country": "USD", "impact": "High",
             "date": "2026-08-07T08:30:00-04:00"}]          # ET summer offset
    b = _acq(rows, tmp_path).refresh(NOW)
    assert b["events"][0]["event_timestamp"] == "2026-08-07T12:30:00Z"


# --------------------------------------------------------------------------- #
# F-5: response hardening
# --------------------------------------------------------------------------- #
def test_oversized_response_rejected(tmp_path):
    huge = json.dumps(week_rows(NOW)) + " " * 10_000
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: huge, now_fn=lambda: NOW,
        max_response_bytes=500)
    with pytest.raises(AcquisitionError) as e:
        prov.fetch(NOW)
    assert e.value.reason == Reason.OVERSIZED_RESPONSE


def test_bad_content_type_rejected(tmp_path):
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: (json.dumps(week_rows(NOW)), "text/html"),
        now_fn=lambda: NOW)
    with pytest.raises(AcquisitionError) as e:
        prov.fetch(NOW)
    assert e.value.reason == Reason.BAD_CONTENT_TYPE


def test_json_content_type_accepted(tmp_path):
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: (json.dumps(week_rows(NOW)), "application/json"),
        now_fn=lambda: NOW)
    raw = prov.fetch(NOW)
    assert len(raw.events) == 3


def test_redirect_guard_rejects_cross_host():
    with pytest.raises(AcquisitionError) as e:
        _check_url_secure("https://evil.example.com/x.json")
    assert e.value.reason == Reason.SOURCE_ERROR


def test_redirect_guard_rejects_https_downgrade():
    with pytest.raises(AcquisitionError) as e:
        _check_url_secure("http://nfs.faireconomy.media/x.json")
    assert e.value.reason == Reason.INSECURE_SCHEME


# --------------------------------------------------------------------------- #
# schema drift
# --------------------------------------------------------------------------- #
def test_schema_field_removed_fails_closed(tmp_path):
    rows = [{"country": "USD", "impact": "High", "date": _iso(NOW)}]   # no title
    with pytest.raises(AcquisitionError) as e:
        _acq(rows, tmp_path).refresh(NOW)
    assert e.value.reason == Reason.MISSING_FIELD


def test_unknown_impact_still_blocks_conservatively(tmp_path):
    rows = [{"title": "Mystery", "country": "USD", "impact": "PURPLE",
             "date": _iso(NOW + timedelta(minutes=5))}]
    svc, out, _ = _ff_service(tmp_path, rows)
    assert svc.refresh_once(NOW) is True
    bundle = FileNewsDataProvider(str(out)).bundle(NOW)
    v = gate_news({"symbol": "EURUSD.FX"}, bundle, NewsLockoutConfig(), NOW)
    assert v.passed is False                          # unknown impact -> HIGH -> blocks


# --------------------------------------------------------------------------- #
# F-3: completeness honesty
# --------------------------------------------------------------------------- #
def test_completeness_not_provable_single_source(tmp_path):
    b = _acq(week_rows(NOW), tmp_path).refresh(NOW)
    assert b["provenance"]["completeness"] == "unestablished"
    assert b["provenance"]["single_source_completeness_not_provable"] is True


# --------------------------------------------------------------------------- #
# F-7: informational result-field conflict recording
# --------------------------------------------------------------------------- #
def test_lockout_conflict_fails_closed(tmp_path):
    ts = _iso(NOW + timedelta(minutes=5))
    rows = [{"title": "NFP", "country": "USD", "impact": "High", "date": ts,
             "event_id": "EID1"},
            {"title": "NFP", "country": "USD", "impact": "Low", "date": ts,
             "event_id": "EID1"}]                     # same id, conflicting impact
    with pytest.raises(AcquisitionError) as e:
        _acq(rows, tmp_path).refresh(NOW)
    assert e.value.reason == Reason.DUPLICATE_CONFLICT


def test_result_field_conflict_recorded_not_silent(tmp_path):
    ts = _iso(NOW + timedelta(minutes=5))
    rows = [{"title": "NFP", "country": "USD", "impact": "High", "date": ts,
             "event_id": "EID1", "forecast": "170K"},
            {"title": "NFP", "country": "USD", "impact": "High", "date": ts,
             "event_id": "EID1", "forecast": "999K"}]  # same lockout id, diff forecast
    b = _acq(rows, tmp_path).refresh(NOW)
    ev = [e for e in b["events"] if e["event_id"] == "EID1"][0]
    assert ev["forecast"] is None                     # conflict -> nulled, not a winner
    assert any("result_conflict_forecast" in w
               for w in b["provenance"]["normalization_warnings"])


# --------------------------------------------------------------------------- #
# F-4 / F-6: lock + health status derivation
# --------------------------------------------------------------------------- #
def test_single_instance_lock_blocks_duplicate(tmp_path):
    lockp = tmp_path / "acq.lock"
    with SingleInstanceLock(lockp):
        with pytest.raises(LockHeld):
            SingleInstanceLock(lockp).acquire()


def test_health_service_stale_derived_externally(tmp_path):
    svc, out, _ = _ff_service(tmp_path, week_rows(NOW))
    svc.refresh_once(NOW)
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["status"] == HEALTH_HEALTHY
    # a monitor checking much later sees the service as stale (no recent attempt)
    later = NOW + timedelta(hours=3)
    assert derive_service_status(status, later) == HEALTH_SERVICE_STALE
    assert derive_service_status(status, NOW + timedelta(minutes=1)) == HEALTH_HEALTHY


# --------------------------------------------------------------------------- #
# §13 MANDATORY end-to-end proofs
# --------------------------------------------------------------------------- #
def test_e2e_current_payload_blocks_high_event(tmp_path):
    svc, out, _ = _ff_service(tmp_path, week_rows(NOW))
    assert svc.refresh_once(NOW) is True
    bundle = FileNewsDataProvider(str(out)).bundle(NOW)      # existing provider
    v = gate_news({"symbol": "EURUSD.FX"}, bundle, NewsLockoutConfig(), NOW)  # existing gate
    assert v.passed is False
    assert any("LOCKOUT" in str(c) or "BLOCKED" in str(c) for c in v.reason_codes)


def test_e2e_stale_payload_rejected_lkg_ages_compliance_blocks(tmp_path):
    """MANDATORY: stale-but-HTTP-200 -> rejected by freshness -> LKG not refreshed ->
    LKG ages -> existing compliance blocks on NEWS_DATA_STALE."""
    # 1) establish a good last-known-good at NOW
    svc, out, _ = _ff_service(tmp_path, week_rows(NOW))
    assert svc.refresh_once(NOW) is True
    good = out.read_text()
    # 2) upstream now serves last week's calendar over HTTP 200, an hour later
    later = NOW + timedelta(hours=1, minutes=5)
    svc.acquirer.provider = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: json.dumps(week_rows(NOW - timedelta(days=7))),
        now_fn=lambda: later)
    assert svc.refresh_once(later) is False
    assert out.read_text() == good                          # LKG preserved, not re-stamped
    # 3) the preserved bundle has aged past compliance max_age -> blocks
    bundle = FileNewsDataProvider(str(out)).bundle(later)
    v = gate_news({"symbol": "EURUSD.FX"}, bundle, NewsLockoutConfig(), later)
    assert v.passed is False
    assert any("STALE" in str(c) for c in v.reason_codes)


def test_service_recovers_after_failure(tmp_path):
    svc, out, _ = _ff_service(tmp_path, week_rows(NOW - timedelta(days=7)))
    assert svc.refresh_once(NOW) is False and not out.exists()
    # provider recovers with the correct current-week calendar
    svc.acquirer.provider = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: json.dumps(week_rows(NOW)), now_fn=lambda: NOW)
    assert svc.refresh_once(NOW) is True and out.exists()


# --------------------------------------------------------------------------- #
# F-1: gated LIVE probe (skipped unless explicitly enabled)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.environ.get("SESSION_EDGE_CALENDAR_LIVE_PROBE") != "1",
                    reason="live provider probe disabled (set SESSION_EDGE_CALENDAR_LIVE_PROBE=1)")
def test_live_forexfactory_probe():
    """Contacts the REAL ForexFactory endpoint (only when explicitly enabled) and
    proves a real payload normalizes + coverage-verifies for the current week."""
    now = datetime.now(timezone.utc)
    prov = ForexFactoryCalendarProvider(now_fn=lambda: now)   # real default fetcher
    cfg = CalendarConfig(enabled=True, provider="forexfactory", output_file="/tmp/x.json",
                         health_file="/tmp/h.json")
    bundle = CalendarAcquirer(prov, cfg).refresh(now)
    assert bundle["provenance"]["coverage_verified"] is True
    assert bundle["provenance"]["event_count"] > 0
    assert bundle["provenance"]["source_name"] == "forexfactory"
