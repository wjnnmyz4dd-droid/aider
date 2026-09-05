"""P1 news-acquisition DIAGNOSTIC ENRICHMENT tests.

Proves the failure detail that previously collapsed into a bare ``ACQ_SOURCE_ERROR``
is now preserved — as STRUCTURED, sanitized fields — through provider -> service ->
status artifact -> operator log, WITHOUT changing any acquisition, freshness, veto,
or recovery behavior, and WITHOUT leaking secrets.

Deterministic; no real network (the HTTP call / opener is injected or fabricated).
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from datetime import timedelta

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance.contract import NewsLockoutConfig
from forex_swing_orb.compliance.news import gate_news
from forex_swing_orb.newsfeed.acquire import CalendarAcquirer
from forex_swing_orb.newsfeed.config import CalendarConfig
from forex_swing_orb.newsfeed.contract import (AcquisitionError, Reason,
                                               format_failure, sanitize_detail)
from forex_swing_orb.newsfeed.http_provider import (_default_fetcher,
                                                    _network_error_detail, _short_repr,
                                                    ForexFactoryCalendarProvider)
from forex_swing_orb.newsfeed.provider import InjectableCalendarProvider
from forex_swing_orb.newsfeed.service import CalendarAcquisitionService

from .conftest import NOW, raw_rows


# --------------------------------------------------------------------------- #
# 1. canonical network-exception -> structured detail mapping
# --------------------------------------------------------------------------- #
def _httperror(code, msg="err"):
    return urllib.error.HTTPError("https://nfs.faireconomy.media/x.json", code, msg,
                                  {}, None)


@pytest.mark.parametrize("code", [403, 429, 500, 503])
def test_http_status_preserved_structurally(code):
    d = _network_error_detail(_httperror(code))
    assert d["http_status"] == code
    assert d["exception_class"] == "HTTPError"


def test_dns_failure_maps_to_underlying_class_and_errno():
    exc = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
    d = _network_error_detail(exc)
    assert d["exception_class"] == "URLError"
    assert d["underlying_class"] == "gaierror"
    assert d["errno"] == -2
    assert "http_status" not in d


def test_tls_failure_maps_to_ssl_class():
    exc = urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))
    d = _network_error_detail(exc)
    assert d["underlying_class"] == "SSLError"


def test_connection_reset_carries_errno():
    exc = urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
    d = _network_error_detail(exc)
    assert d["underlying_class"] == "ConnectionResetError" and d["errno"] == 104


def test_connection_refused_carries_errno():
    exc = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    d = _network_error_detail(exc)
    assert d["underlying_class"] == "ConnectionRefusedError" and d["errno"] == 111


def test_winerror_preserved_when_present():
    under = OSError("Access is denied"); under.errno = 13; under.winerror = 10061
    d = _network_error_detail(urllib.error.URLError(under))
    assert d["winerror"] == 10061 and d["errno"] == 13


def test_generic_oserror_still_has_class_and_bounded_error():
    d = _network_error_detail(OSError(28, "No space left on device"))
    assert d["exception_class"] == "OSError" and d["errno"] == 28
    assert isinstance(d["error"], str)


def test_unknown_exception_without_errno_winerror_is_structured_not_crashing():
    class Weird(Exception):
        pass
    d = _network_error_detail(Weird("boom"))
    assert d["exception_class"] == "Weird"
    assert "errno" not in d and "winerror" not in d and "http_status" not in d


def test_short_repr_is_bounded():
    class Big:
        def __repr__(self):
            return "x" * 5000
    s = _short_repr(Big())
    assert len(s) <= 320 and s.endswith("...(truncated)")


def test_short_repr_survives_hostile_repr():
    class Hostile:
        def __repr__(self):
            raise RuntimeError("nope")
    assert "unrepr-able" in _short_repr(Hostile())


# --------------------------------------------------------------------------- #
# 2. _default_fetcher end-to-end mapping (opener fabricated; NO network)
# --------------------------------------------------------------------------- #
class _RaisingOpener:
    def __init__(self, exc):
        self._exc = exc

    def open(self, req, timeout=None):
        raise self._exc


def _patch_opener(monkeypatch, exc):
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _RaisingOpener(exc))


def test_default_fetcher_http_429_becomes_source_error_with_status(monkeypatch):
    _patch_opener(monkeypatch, _httperror(429, "Too Many Requests"))
    with pytest.raises(AcquisitionError) as e:
        _default_fetcher("https://nfs.faireconomy.media/ff_calendar_thisweek.json", 5, 1000)
    assert e.value.reason == Reason.SOURCE_ERROR
    assert e.value.detail["http_status"] == 429


def test_default_fetcher_dns_becomes_source_error_with_underlying(monkeypatch):
    _patch_opener(monkeypatch, urllib.error.URLError(socket.gaierror(-2, "no name")))
    with pytest.raises(AcquisitionError) as e:
        _default_fetcher("https://nfs.faireconomy.media/ff_calendar_thisweek.json", 5, 1000)
    assert e.value.reason == Reason.SOURCE_ERROR
    assert e.value.detail["underlying_class"] == "gaierror"


def test_default_fetcher_timeout_classified_as_acq_timeout(monkeypatch):
    _patch_opener(monkeypatch, urllib.error.URLError(TimeoutError("timed out")))
    with pytest.raises(AcquisitionError) as e:
        _default_fetcher("https://nfs.faireconomy.media/ff_calendar_thisweek.json", 5, 1000)
    assert e.value.reason == Reason.TIMEOUT          # distinct from SOURCE_ERROR


# --------------------------------------------------------------------------- #
# 3. sanitizer / formatter (privacy + rendering)
# --------------------------------------------------------------------------- #
def test_sanitize_redacts_credential_shaped_values():
    d = sanitize_detail({"error": "URLError(...token=abcd1234...)", "http_status": 429})
    assert d["error"] == "[REDACTED]" and d["http_status"] == 429


def test_sanitize_truncates_long_values():
    d = sanitize_detail({"error": "y" * 1000})
    assert len(d["error"]) <= 320 and d["error"].endswith("...(truncated)")


def test_format_failure_renders_key_values():
    s = format_failure(Reason.SOURCE_ERROR, {"http_status": 429})
    assert s.startswith("code=ACQ_SOURCE_ERROR") and "http_status=429" in s


# --------------------------------------------------------------------------- #
# 4. service integration: detail reaches health + log; success clears it
# --------------------------------------------------------------------------- #
def _cfg(tmp_path, **over):
    out = tmp_path / "news.json"
    base = dict(enabled=True, provider="forexfactory", output_file=str(out),
                health_file=str(tmp_path / "calendar_acq_status.json"), refresh_sec=1800,
                max_source_age_sec=21600, max_clock_skew_sec=120, source_file=None,
                static_trusted=False, timeout_sec=12.0, retries=0, backoff_sec=0,
                log_file=None)
    base.update(over)
    return CalendarConfig(**base), out


def _svc(tmp_path, provider, **over):
    cfg, out = _cfg(tmp_path, **over)
    svc = CalendarAcquisitionService(CalendarAcquirer(provider, cfg), cfg,
                                     now_fn=lambda: NOW, sleep_fn=lambda s: None)
    return svc, out, cfg


def _failing_provider(reason, detail):
    return InjectableCalendarProvider(
        lambda now: (_ for _ in ()).throw(AcquisitionError(reason, detail)))


def _good_provider():
    return ForexFactoryCalendarProvider(
        fetcher=lambda url, timeout, max_bytes: (json.dumps(raw_rows()), "application/json"),
        now_fn=lambda: NOW)


def test_health_records_structured_detail_on_source_error(tmp_path):
    svc, out, cfg = _svc(tmp_path, _failing_provider(Reason.SOURCE_ERROR,
                                                     {"http_status": 429}))
    assert svc.refresh_once(NOW) is False
    hs = json.loads((tmp_path / "calendar_acq_status.json").read_text())
    assert hs["last_failure_reason"] == Reason.SOURCE_ERROR
    assert hs["last_failure_detail"]["http_status"] == 429


def test_operator_log_carries_status_and_disposition(tmp_path, caplog):
    svc, out, cfg = _svc(tmp_path, _failing_provider(Reason.SOURCE_ERROR,
                                                     {"http_status": 429}))
    with caplog.at_level("WARNING", logger="session_edge.calendar"):
        svc.refresh_once(NOW)
    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "http_status=429" in msg and "disposition=FAIL_CLOSED" in msg
    assert "last_known_good_preserved" in msg


def test_success_clears_last_failure_detail(tmp_path):
    svc, out, cfg = _svc(tmp_path, _failing_provider(Reason.SOURCE_ERROR,
                                                     {"http_status": 500}))
    assert svc.refresh_once(NOW) is False
    hs = json.loads((tmp_path / "calendar_acq_status.json").read_text())
    assert hs["last_failure_detail"]["http_status"] == 500
    svc.acquirer.provider = _good_provider()             # provider recovers (HTTP 200)
    assert svc.refresh_once(NOW) is True
    hs = json.loads((tmp_path / "calendar_acq_status.json").read_text())
    assert hs["healthy"] is True and hs["last_failure_detail"] is None


def test_secret_never_written_to_status_file(tmp_path):
    svc, out, cfg = _svc(tmp_path, _failing_provider(
        Reason.SOURCE_ERROR, {"error": "URLError token=SUPERSECRET123 host=..."}))
    svc.refresh_once(NOW)
    blob = (tmp_path / "calendar_acq_status.json").read_text().lower()
    for secret in ("supersecret123", "token=", "password", "apikey"):
        assert secret not in blob


# --------------------------------------------------------------------------- #
# 5. behavior UNCHANGED: LKG preserved, NEWS_DATA_STALE veto, recovery
# --------------------------------------------------------------------------- #
def test_lkg_preserved_and_bundle_unchanged_on_failure(tmp_path):
    svc, out, cfg = _svc(tmp_path, _good_provider())
    assert svc.refresh_once(NOW) is True
    first = out.read_text(encoding="utf-8")
    svc.acquirer.provider = _failing_provider(Reason.SOURCE_ERROR, {"http_status": 429})
    assert svc.refresh_once(NOW) is False
    assert out.read_text(encoding="utf-8") == first      # byte-identical LKG preserved


def test_stale_lkg_still_vetoes_with_news_data_stale(tmp_path):
    # Acquire once, then let the provider fail; the preserved bundle's content as_of
    # must still trip NEWS_DATA_STALE once older than max_age_sec (veto UNCHANGED).
    svc, out, cfg = _svc(tmp_path, _good_provider())
    assert svc.refresh_once(NOW) is True
    svc.acquirer.provider = _failing_provider(Reason.SOURCE_ERROR, {"http_status": 429})
    assert svc.refresh_once(NOW) is False
    ok, bundle = serialize.loads(out.read_text(encoding="utf-8"))
    assert ok
    ncfg = NewsLockoutConfig()                           # max_age_sec = 3600
    much_later = NOW + timedelta(hours=3)
    verdict = gate_news({"symbol": "EURUSD"}, bundle, ncfg, much_later)
    assert verdict.passed is False
    assert "NEWS_DATA_STALE" in verdict.reason_codes


def test_fresh_bundle_after_recovery_unblocks(tmp_path):
    svc, out, cfg = _svc(tmp_path, _good_provider())
    assert svc.refresh_once(NOW) is True
    ok, bundle = serialize.loads(out.read_text(encoding="utf-8"))
    assert ok
    ncfg = NewsLockoutConfig()
    # a fresh bundle evaluated shortly after (before any lockout window) is not stale
    verdict = gate_news({"symbol": "AUDCAD"}, bundle, ncfg, NOW + timedelta(minutes=1))
    assert "NEWS_DATA_STALE" not in verdict.reason_codes


# --------------------------------------------------------------------------- #
# 6. diagnostic never weakens the failure path
# --------------------------------------------------------------------------- #
def test_lkg_age_helper_never_raises_and_returns_none_when_absent(tmp_path):
    svc, out, cfg = _svc(tmp_path, _good_provider())
    assert svc._last_known_good_age_sec(NOW) is None      # no bundle written yet


def test_failure_still_returns_false_even_if_detail_is_weird(tmp_path):
    # a non-serializable-ish / odd detail must not turn a failure into success
    svc, out, cfg = _svc(tmp_path, _failing_provider(Reason.SOURCE_ERROR,
                                                     {"error": object()}))
    assert svc.refresh_once(NOW) is False
