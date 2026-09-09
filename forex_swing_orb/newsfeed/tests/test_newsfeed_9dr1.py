"""Phase 9D-R1 — autonomous economic-calendar acquisition tests.

Deterministic; NO network access (the network provider's HTTP call is injected).
Covers: normalization (incl. impact D-2), provenance, freshness, failure modes,
atomic write + last-known-good, restart, the end-to-end integration into the
EXISTING compliance news gate, config, and the network/authority/security
boundaries.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import NewsLockoutConfig
from forex_swing_orb.compliance.news import gate_news
from forex_swing_orb.live.providers import FileNewsDataProvider
from forex_swing_orb.newsfeed import normalize
from forex_swing_orb.newsfeed.acquire import CalendarAcquirer
from forex_swing_orb.newsfeed.config import CalendarConfig, load_calendar_config
from forex_swing_orb.newsfeed.contract import (SCHEMA_VERSION, AcquisitionError,
                                               RawCalendar, Reason)
from forex_swing_orb.newsfeed.http_provider import (_ALLOWED_HOST, _default_fetcher,
                                                    ForexFactoryCalendarProvider)
from forex_swing_orb.newsfeed.provider import (InjectableCalendarProvider,
                                               StaticFileCalendarProvider)
from forex_swing_orb.newsfeed.service import CalendarAcquisitionService, build_provider

from .conftest import NOW, raw_rows


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _cfg(**over):
    base = dict(enabled=True, provider="static", output_file="/x/news.json",
                health_file="/x/health.json", refresh_sec=1800,
                max_source_age_sec=21600, max_clock_skew_sec=120,
                source_file=None, static_trusted=False, timeout_sec=12.0,
                retries=2, backoff_sec=2.0, log_file=None)
    base.update(over)
    return CalendarConfig(**base)


def _raw(rows=None, *, fetched_at=NOW, source_as_of=None, complete=None, trusted=True):
    return RawCalendar(source_name="test", source_identifier="test.json",
                       provider_version="test.v1", fetched_at=fetched_at,
                       events=tuple(rows if rows is not None else raw_rows()),
                       source_as_of=source_as_of, complete=complete, trusted=trusted)


def _acquirer(rows=None, *, trusted=True, **rawkw):
    prov = InjectableCalendarProvider(lambda now: _raw(rows, trusted=trusted, **rawkw),
                                      trusted=trusted)
    return CalendarAcquirer(prov, _cfg())


# --------------------------------------------------------------------------- #
# 1. normalization + impact (D-2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("HIGH", "HIGH"), ("High", "HIGH"), ("high", "HIGH"), ("H", "HIGH"),
    ("3", "HIGH"), ("RED", "HIGH"), ("red", "HIGH"),
    ("Medium", "MEDIUM"), ("2", "MEDIUM"), ("orange", "MEDIUM"),
    ("Low", "LOW"), ("1", "LOW"), ("Holiday", "LOW"), ("Non-Economic", "LOW"),
])
def test_impact_canonicalization(raw, expected):
    imp, warning = normalize.normalize_impact(raw)
    assert imp == expected and warning is None


def test_unknown_impact_is_conservative_high_never_downgraded():
    imp, warning = normalize.normalize_impact("PURPLE")
    assert imp == "HIGH"                       # conservative over-block
    assert "PURPLE" in warning and "HIGH" in warning


def test_missing_impact_maps_conservative_high():
    imp, warning = normalize.normalize_impact(None)
    assert imp == "HIGH" and warning is not None


def test_currency_from_country_field_and_validation():
    ev, _ = normalize.normalize_event(
        {"title": "X", "country": "usd", "impact": "High",
         "date": "2024-01-10T12:10:00+00:00"}, "src", True)
    assert ev["currency"] == "USD" and ev["verification_state"] == "VERIFIED"


def test_invalid_currency_fails_closed():
    with pytest.raises(AcquisitionError) as e:
        normalize.normalize_event({"title": "X", "country": "US1", "impact": "High",
                                   "date": "2024-01-10T12:10:00+00:00"}, "src", True)
    assert e.value.reason == Reason.INVALID_CURRENCY


def test_missing_required_field_fails_closed():
    with pytest.raises(AcquisitionError) as e:
        normalize.normalize_event({"country": "USD", "impact": "High",
                                   "date": "2024-01-10T12:10:00+00:00"}, "src", True)
    assert e.value.reason == Reason.MISSING_FIELD


def test_invalid_timestamp_fails_closed():
    with pytest.raises(AcquisitionError) as e:
        normalize.normalize_event({"title": "X", "country": "USD", "impact": "High",
                                   "date": "not-a-date"}, "src", True)
    assert e.value.reason == Reason.INVALID_TIMESTAMP


def test_result_fields_preserved_and_missing_are_null():
    ev, _ = normalize.normalize_event(
        {"title": "X", "country": "USD", "impact": "High",
         "date": "2024-01-10T12:10:00+00:00", "forecast": "1.1", "previous": "1.0"},
        "src", True)
    assert ev["forecast"] == "1.1" and ev["previous"] == "1.0"
    assert ev["actual"] is None and ev["revision"] is None


def test_non_finite_result_field_fails_closed():
    with pytest.raises(AcquisitionError) as e:
        normalize.normalize_event({"title": "X", "country": "USD", "impact": "High",
                                   "date": "2024-01-10T12:10:00+00:00",
                                   "forecast": float("inf")}, "src", True)
    assert e.value.reason == Reason.NON_FINITE


def test_stable_event_id_is_deterministic():
    a = normalize.stable_event_id("ff", "USD", "NFP", "2024-01-10T12:10:00Z")
    b = normalize.stable_event_id("ff", "USD", "NFP", "2024-01-10T12:10:00Z")
    assert a == b and len(a) == 16


def test_untrusted_source_marks_events_unverified():
    ev, _ = normalize.normalize_event({"title": "X", "country": "USD", "impact": "High",
                                       "date": "2024-01-10T12:10:00+00:00"}, "src", False)
    assert ev["verification_state"] == "UNVERIFIED"


# --------------------------------------------------------------------------- #
# 2. provenance + bundle shape + integrity
# --------------------------------------------------------------------------- #
def test_bundle_has_full_provenance_and_integrity(now):
    bundle = _acquirer().refresh(now)
    for k in ("as_of", "verified", "events", "provenance", "schema_version"):
        assert k in bundle
    prov = bundle["provenance"]
    for k in ("source_name", "source_identifier", "source_as_of", "fetched_at",
              "normalized_at", "bundle_as_of", "provider_version", "schema_version",
              "completeness", "event_count", "normalization_warnings"):
        assert k in prov
    assert bundle["schema_version"] == SCHEMA_VERSION
    assert serialize.verify_integrity_digest(bundle)


def test_completeness_reported_honestly(now):
    assert _acquirer().refresh(now)["provenance"]["completeness"] == "unestablished"
    prov = _acquirer(complete=True).refresh(now)["provenance"]
    assert prov["completeness"] == "source_declared"


def test_events_carry_stable_identity_and_result_fields(now):
    ev = _acquirer().refresh(now)["events"][0]
    assert ev["event_id"] and ev["source_event_key"]
    assert set(("previous", "forecast", "actual", "revision")).issubset(ev)


# --------------------------------------------------------------------------- #
# 3. freshness / failure modes
# --------------------------------------------------------------------------- #
def test_empty_payload_fails_closed(now):
    with pytest.raises(AcquisitionError) as e:
        _acquirer(rows=[]).refresh(now)
    assert e.value.reason == Reason.EMPTY_PAYLOAD


def test_future_fetched_beyond_skew_fails_closed(now):
    acq = _acquirer(fetched_at=now + timedelta(seconds=600))
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(now)
    assert e.value.reason == Reason.FUTURE_SOURCE_TIME


def test_future_source_as_of_fails_closed(now):
    acq = _acquirer(source_as_of=now + timedelta(hours=1))
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(now)
    assert e.value.reason == Reason.FUTURE_SOURCE_TIME


def test_stale_source_as_of_fails_closed(now):
    acq = _acquirer(source_as_of=now - timedelta(hours=7))
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(now)
    assert e.value.reason == Reason.STALE_SOURCE


def test_duplicate_conflict_fails_closed(now):
    rows = [
        {"title": "NFP", "country": "USD", "impact": "High",
         "date": "2024-01-10T12:10:00+00:00"},
        {"title": "NFP", "country": "USD", "impact": "Low",     # same id, diff impact
         "date": "2024-01-10T12:10:00+00:00"},
    ]
    with pytest.raises(AcquisitionError) as e:
        _acquirer(rows=rows).refresh(now)
    assert e.value.reason == Reason.DUPLICATE_CONFLICT


def test_identical_duplicate_is_deduped_not_conflict(now):
    row = {"title": "NFP", "country": "USD", "impact": "High",
           "date": "2024-01-10T12:10:00+00:00"}
    bundle = _acquirer(rows=[row, dict(row)]).refresh(now)
    assert bundle["provenance"]["event_count"] == 1


def test_provider_unavailable_fails_closed(now, tmp_path):
    prov = StaticFileCalendarProvider(str(tmp_path / "missing.json"))
    with pytest.raises(AcquisitionError) as e:
        CalendarAcquirer(prov, _cfg()).refresh(now)
    assert e.value.reason == Reason.PROVIDER_UNAVAILABLE


def test_malformed_payload_fails_closed(now, tmp_path):
    p = tmp_path / "raw.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(AcquisitionError) as e:
        CalendarAcquirer(StaticFileCalendarProvider(str(p)), _cfg()).refresh(now)
    assert e.value.reason == Reason.MALFORMED_PAYLOAD


def test_injected_source_error_wraps_fail_closed(now):
    def boom(_now):
        raise RuntimeError("network down")
    acq = CalendarAcquirer(InjectableCalendarProvider(boom), _cfg())
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(now)
    assert e.value.reason == Reason.SOURCE_ERROR


def test_injected_timeout_propagates(now):
    def timeout(_now):
        raise AcquisitionError(Reason.TIMEOUT, {})
    acq = CalendarAcquirer(InjectableCalendarProvider(timeout), _cfg())
    with pytest.raises(AcquisitionError) as e:
        acq.refresh(now)
    assert e.value.reason == Reason.TIMEOUT


# --------------------------------------------------------------------------- #
# 4. ForexFactory provider (no network — fetch injected) + host lock
# --------------------------------------------------------------------------- #
def test_forexfactory_parses_injected_payload(now):
    prov = ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: json.dumps(raw_rows()), now_fn=lambda: now)
    raw = prov.fetch(now)
    assert raw.source_name == "forexfactory" and raw.trusted is True
    assert raw.complete is None and len(raw.events) == 2


def test_forexfactory_malformed_payload_fails_closed(now):
    prov = ForexFactoryCalendarProvider(fetcher=lambda url, timeout, max_bytes: "<<garbage",
                                        now_fn=lambda: now)
    with pytest.raises(AcquisitionError) as e:
        prov.fetch(now)
    assert e.value.reason == Reason.MALFORMED_PAYLOAD


def test_forexfactory_fetcher_error_fails_closed(now):
    def boom(url, timeout, max_bytes):
        raise OSError("connection refused")
    prov = ForexFactoryCalendarProvider(fetcher=boom, now_fn=lambda: now)
    with pytest.raises(AcquisitionError) as e:
        prov.fetch(now)
    assert e.value.reason == Reason.PROVIDER_UNAVAILABLE


def test_default_fetcher_rejects_disallowed_host_without_network():
    # Non-allowlisted host must raise before any network I/O is attempted.
    with pytest.raises(AcquisitionError) as e:
        _default_fetcher("https://evil.example.com/x.json", 1.0, 1000)
    assert e.value.reason == Reason.SOURCE_ERROR
    assert _ALLOWED_HOST == "nfs.faireconomy.media"


# --------------------------------------------------------------------------- #
# 5. atomic write + last-known-good + restart
# --------------------------------------------------------------------------- #
def _service(tmp_path, prov, **cfgover):
    out = tmp_path / "news.json"
    health = tmp_path / "calendar_acq_status.json"
    params = dict(output_file=str(out), health_file=str(health), refresh_sec=10,
                  retries=1, backoff_sec=0)
    params.update(cfgover)
    cfg = _cfg(**params)
    svc = CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                     now_fn=lambda: NOW, sleep_fn=lambda s: None)
    return svc, out, health


def test_refresh_writes_bundle_and_health(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, health = _service(tmp_path, prov)
    assert svc.refresh_once(NOW) is True
    ok, bundle = serialize.loads(out.read_text(encoding="utf-8"))
    assert ok and bundle["provenance"]["event_count"] == 2
    hs = json.loads(health.read_text(encoding="utf-8"))
    assert hs["healthy"] is True and hs["provider"] == "static"
    # no stray temp file remains
    assert not list(tmp_path.glob(".*.tmp"))


def test_failed_refresh_preserves_last_known_good(tmp_path):
    good = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, health = _service(tmp_path, good)
    assert svc.refresh_once(NOW) is True
    first = out.read_text(encoding="utf-8")
    # now swap in a failing provider and refresh again
    svc.acquirer.provider = InjectableCalendarProvider(
        lambda now: (_ for _ in ()).throw(AcquisitionError(Reason.SOURCE_ERROR, {})))
    assert svc.refresh_once(NOW) is False
    assert out.read_text(encoding="utf-8") == first          # unchanged LKG
    hs = json.loads(health.read_text(encoding="utf-8"))
    assert hs["healthy"] is False and hs["last_failure_reason"] == Reason.SOURCE_ERROR


def test_write_failure_preserves_and_reports(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    cfg = _cfg(output_file=str(tmp_path / "nodir" / "news.json"),
               health_file=str(tmp_path / "h.json"), refresh_sec=10, retries=0,
               backoff_sec=0)
    svc = CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                     now_fn=lambda: NOW, sleep_fn=lambda s: None)
    assert svc.refresh_once(NOW) is False
    hs = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
    assert hs["last_failure_reason"] == Reason.WRITE_FAILED
    assert not (tmp_path / "nodir" / "news.json").exists()


def test_retries_then_success(tmp_path):
    calls = {"n": 0}

    def flaky(now):
        calls["n"] += 1
        if calls["n"] < 2:
            raise AcquisitionError(Reason.TIMEOUT, {})
        return _raw()
    svc, out, _ = _service(tmp_path, InjectableCalendarProvider(flaky), retries=3)
    assert svc.refresh_once(NOW) is True and calls["n"] == 2


def test_no_overlapping_refresh(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, _, _ = _service(tmp_path, prov)
    svc._busy = True
    assert svc.refresh_once(NOW) is False       # guarded


def test_run_forever_max_cycles(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, _ = _service(tmp_path, prov)
    svc.run_forever(max_cycles=2)
    assert out.exists()


def test_clean_shutdown_via_signal_flag(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, _, _ = _service(tmp_path, prov)
    svc._handle_signal()
    assert svc._stop is True
    svc.run_forever(max_cycles=5)               # returns promptly, no hang


def test_disabled_service_does_nothing(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, _ = _service(tmp_path, prov, enabled=False)
    svc.run_forever(max_cycles=3)
    assert not out.exists()


def test_preserved_bundle_eventually_goes_stale_in_compliance(tmp_path):
    """A preserved last-known-good file cannot keep trading alive: once it ages past
    the compliance max_age it fails closed there."""
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, _ = _service(tmp_path, prov)
    svc.refresh_once(NOW)
    bundle = FileNewsDataProvider(str(out)).bundle(NOW)
    later = NOW + timedelta(hours=2)            # > default 3600s max_age
    verdict = gate_news({"symbol": "EURUSD.FX"}, bundle, NewsLockoutConfig(), later)
    assert verdict.passed is False
    assert any("STALE" in str(c) for c in verdict.reason_codes)


# --------------------------------------------------------------------------- #
# 6. END-TO-END integration into the EXISTING compliance news gate
# --------------------------------------------------------------------------- #
def test_e2e_high_event_blocks_relevant_pair(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, _ = _service(tmp_path, prov)
    assert svc.refresh_once(NOW) is True
    bundle = FileNewsDataProvider(str(out)).bundle(NOW)     # existing provider reads it
    verdict = gate_news({"symbol": "EURUSD.FX"}, bundle, NewsLockoutConfig(), NOW)
    assert verdict.passed is False                          # USD NFP in-window blocks
    assert any("LOCKOUT" in str(c) or "BLOCKED" in str(c) for c in verdict.reason_codes)


def test_e2e_unrelated_currency_does_not_block(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, _ = _service(tmp_path, prov)
    svc.refresh_once(NOW)
    bundle = FileNewsDataProvider(str(out)).bundle(NOW)
    verdict = gate_news({"symbol": "GBPJPY.FX"}, bundle, NewsLockoutConfig(), NOW)
    assert verdict.passed is True                           # neither GBP nor JPY event


def test_disabling_layer_leaves_manual_file_workflow_intact(tmp_path):
    """The existing manual FileNewsDataProvider workflow is untouched: a hand-written
    bundle still reads and gates exactly as before, with no acquisition layer."""
    manual = tmp_path / "manual_news.json"
    bundle = {"as_of": serialize.iso_utc(NOW), "verified": True, "events": []}
    manual.write_text(serialize.canonical_json(bundle), encoding="utf-8")
    read = FileNewsDataProvider(str(manual)).bundle(NOW)
    verdict = gate_news({"symbol": "EURUSD.FX"}, read, NewsLockoutConfig(), NOW)
    assert verdict.passed is True and read["events"] == []


# --------------------------------------------------------------------------- #
# 7. config (fail-closed, no silent selection)
# --------------------------------------------------------------------------- #
def test_config_enabled_requires_explicit_provider():
    with pytest.raises(AcquisitionError) as e:
        load_calendar_config(env={"SESSION_EDGE_CALENDAR_ENABLED": "true",
                                  "SESSION_EDGE_NEWS_FILE": "/x/news.json"})
    assert e.value.reason == Reason.CONFIG_ERROR


def test_config_unknown_provider_fails():
    with pytest.raises(AcquisitionError):
        load_calendar_config(env={"SESSION_EDGE_CALENDAR_ENABLED": "true",
                                  "SESSION_EDGE_CALENDAR_PROVIDER": "bloomberg",
                                  "SESSION_EDGE_NEWS_FILE": "/x/news.json"})


def test_config_static_requires_source_file():
    with pytest.raises(AcquisitionError):
        load_calendar_config(env={"SESSION_EDGE_CALENDAR_ENABLED": "true",
                                  "SESSION_EDGE_CALENDAR_PROVIDER": "static",
                                  "SESSION_EDGE_NEWS_FILE": "/x/news.json"})


def test_config_unknown_json_key_fails(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"totally_unknown": 1}), encoding="utf-8")
    with pytest.raises(AcquisitionError):
        load_calendar_config(env={}, config_path=str(p))


def test_config_defaults_when_disabled():
    cfg = load_calendar_config(env={})
    assert cfg.enabled is False and cfg.refresh_sec == 1800


def test_config_output_defaults_to_news_file():
    cfg = load_calendar_config(env={"SESSION_EDGE_CALENDAR_ENABLED": "true",
                                    "SESSION_EDGE_CALENDAR_PROVIDER": "forexfactory",
                                    "SESSION_EDGE_NEWS_FILE": "/x/news.json"})
    assert cfg.output_file == "/x/news.json"
    assert cfg.health_file.endswith("calendar_acq_status.json")


def test_build_provider_no_silent_selection():
    with pytest.raises(AcquisitionError):
        build_provider(_cfg(provider="nope"))


# --------------------------------------------------------------------------- #
# 8. network / authority / security boundaries
# --------------------------------------------------------------------------- #
import pathlib


def _newsfeed_sources():
    root = pathlib.Path(__file__).resolve().parents[1]
    return [p for p in root.glob("*.py")]


def test_networking_only_in_http_provider():
    # match real import/usage patterns (not the word "sockets" in a docstring)
    tokens = ("import urllib", "urllib.request", "urllib.error", "urlopen",
              "import socket", "socket.socket", "import requests", "requests.",
              "http.client", "httpx", "aiohttp", "websocket")
    for p in _newsfeed_sources():
        if p.name == "http_provider.py":
            continue
        text = p.read_text(encoding="utf-8")
        for t in tokens:
            assert t not in text, f"networking token {t!r} leaked into {p.name}"


def test_no_trade_authority_anywhere_in_newsfeed():
    forbidden = ("order_send", "OrderSend", "write_instruction", "position_close",
                 "PositionClose", "positions_get", "modify_stop", "PositionModify",
                 "build_instruction", "bridge_root")
    for p in _newsfeed_sources():
        text = p.read_text(encoding="utf-8")
        for t in forbidden:
            assert t not in text, f"trade-authority token {t!r} in {p.name}"


def test_health_never_contains_credentials(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, _, health = _service(tmp_path, prov)
    svc.refresh_once(NOW)
    text = health.read_text(encoding="utf-8").lower()
    for bad in ("password", "secret", "token", "api_key", "apikey", "credential"):
        assert bad not in text


def test_bundle_never_contains_credentials(tmp_path):
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc, out, _ = _service(tmp_path, prov)
    svc.refresh_once(NOW)
    text = out.read_text(encoding="utf-8").lower()
    for bad in ("password", "secret", "token", "api_key", "credential"):
        assert bad not in text
