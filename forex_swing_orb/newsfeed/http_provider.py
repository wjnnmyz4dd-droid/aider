"""ForexFactory economic-calendar provider (Phase 9D-R1-R) — THE network boundary.

The ONLY module in Session Edge that performs outbound networking, for calendar
DATA acquisition only. It never trades or touches compliance/risk/positions/bridge/
EA. Selected source: ForexFactory's free weekly JSON calendar — no API key; observed
[LIVE] to return HTTP 200 ``application/json`` with fields
``title/country/impact/date/forecast/previous`` and impacts ``High/Medium/Low/
Holiday`` (no upstream generated timestamp — hence the coverage-based freshness model
in ``freshness.py``).

Hardened network seam (F-5):
  * HTTPS + fixed host allow-list — no arbitrary/caller URL, no HTTP.
  * Redirects refused to any other host AND on any HTTPS->HTTP downgrade.
  * Bounded read that rejects an oversized response before unbounded memory use.
  * Content-Type validated as JSON when the source supplies one.
  * Bounded timeout. Response parsed as inert JSON only. The HTTP call is injected
    (``fetcher``) so tests never touch the network.

Completeness (F-3): the weekly feed gives no completeness guarantee -> ``complete``
is None (unestablished); never claimed from a successful request.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .contract import AcquisitionError, RawCalendar, Reason
from .provider import CalendarProvider

_ALLOWED_HOST = "nfs.faireconomy.media"
_ENDPOINTS = {
    "thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "nextweek": "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
}
_DEFAULT_MAX_BYTES = 5_000_000


def _short_repr(obj, limit=300):
    """Bounded repr so a diagnostic string can never balloon the log/status file."""
    try:
        s = repr(obj)
    except Exception:                          # a hostile __repr__ must not crash us
        return "<unrepr-able %s>" % type(obj).__name__
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def _network_error_detail(exc):
    """Canonical, STRUCTURED, sanitized detail for a network exception raised during
    acquisition — so the operator can distinguish HTTP 403/429/5xx from DNS / TLS /
    connection-reset / connection-refused WITHOUT parsing human-readable strings
    downstream.

    Captures, where the OS/stdlib supplies them: the exception class, the HTTP status
    (``urllib.error.HTTPError.code``), the wrapped OSError class
    (``URLError.reason``), and ``errno`` / ``winerror``. Contains no request headers,
    response body, or credentials (the free weekly endpoint carries none); the
    bounded repr is additionally scrubbed by :func:`contract.sanitize_detail` before
    it is logged or persisted."""
    detail = {"exception_class": type(exc).__name__, "error": _short_repr(exc)}
    code = getattr(exc, "code", None)          # HTTPError carries the HTTP status here
    if isinstance(code, int):
        detail["http_status"] = code
    underlying = getattr(exc, "reason", None)  # URLError wraps gaierror/OSError/SSLError
    if underlying is not None and not isinstance(underlying, str) and underlying is not exc:
        detail["underlying_class"] = type(underlying).__name__
    for src in (underlying, exc):
        if src is None or isinstance(src, str):
            continue
        for attr in ("errno", "winerror"):
            v = getattr(src, attr, None)
            if isinstance(v, int) and attr not in detail:
                detail[attr] = v
    return detail


def _check_url_secure(url):
    """Raise unless ``url`` is HTTPS on the allow-listed host (no network). Shared by
    the initial request and the redirect guard so both enforce the same policy."""
    from urllib.parse import urlparse
    p = urlparse(url)
    if p.scheme != "https":
        raise AcquisitionError(Reason.INSECURE_SCHEME, {"url_scheme": p.scheme, "url": url})
    if p.hostname != _ALLOWED_HOST:
        raise AcquisitionError(Reason.SOURCE_ERROR, {"disallowed_host": p.hostname})
    return True


def _default_fetcher(url, timeout, max_bytes):  # pragma: no cover - real network only
    """Hardened GET. HTTPS + host-locked; refuses cross-host / downgrade redirects;
    bounded read; returns ``(text, content_type)``."""
    import urllib.error
    import urllib.request

    _check_url_secure(url)

    class _StrictRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            _check_url_secure(newurl)          # reject cross-host + HTTPS->HTTP downgrade
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_StrictRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "SessionEdge-Calendar/1.0"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                raise AcquisitionError(Reason.SOURCE_ERROR,
                                       {"http_status": resp.status})
            ctype = resp.headers.get("Content-Type")
            data = resp.read(max_bytes + 1)          # bounded read (no unbounded memory)
            if len(data) > max_bytes:
                raise AcquisitionError(Reason.OVERSIZED_RESPONSE, {"max_bytes": max_bytes})
            return data.decode("utf-8"), ctype
    except urllib.error.URLError as exc:
        underlying = getattr(exc, "reason", None)
        is_timeout = isinstance(underlying, TimeoutError) or "timed out" in str(exc).lower()
        reason = Reason.TIMEOUT if is_timeout else Reason.SOURCE_ERROR
        raise AcquisitionError(reason, _network_error_detail(exc))


class ForexFactoryCalendarProvider(CalendarProvider):
    """Fetches + shallow-parses the ForexFactory weekly JSON into a RawCalendar.

    ``fetcher(url, timeout, max_bytes) -> str | (str, content_type)`` is injected for
    tests; production uses the hardened default. ``now_fn`` supplies fetched_at."""

    name = "forexfactory"
    version = "forexfactory.v1"
    trusted = True

    def __init__(self, *, window="thisweek", timeout=12.0, fetcher=None, now_fn=None,
                 max_response_bytes=_DEFAULT_MAX_BYTES):
        if window not in _ENDPOINTS:
            raise AcquisitionError(Reason.CONFIG_ERROR, {"window": window})
        self.window = window
        self.timeout = float(timeout)
        self.max_bytes = int(max_response_bytes)
        self._fetch_url = fetcher or _default_fetcher
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def fetch(self, now=None):
        url = _ENDPOINTS[self.window]
        try:
            result = self._fetch_url(url, self.timeout, self.max_bytes)
        except AcquisitionError:
            raise
        except Exception as exc:                       # noqa: BLE001 - fail closed
            raise AcquisitionError(Reason.PROVIDER_UNAVAILABLE, {"error": repr(exc)})

        text, ctype = (result if isinstance(result, tuple) else (result, None))
        if ctype is not None and "json" not in str(ctype).lower():
            raise AcquisitionError(Reason.BAD_CONTENT_TYPE, {"content_type": ctype})
        if len(text.encode("utf-8")) > self.max_bytes:   # guard injected fetchers too
            raise AcquisitionError(Reason.OVERSIZED_RESPONSE, {"max_bytes": self.max_bytes})
        try:
            rows = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"error": repr(exc)})
        if not isinstance(rows, list):
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"type": type(rows).__name__})
        return RawCalendar(
            source_name=self.name, source_identifier=f"ff_calendar_{self.window}.json",
            provider_version=self.version, fetched_at=self._now(),
            events=tuple(rows), source_as_of=None,       # weekly feed carries no as_of
            complete=None, trusted=self.trusted)         # completeness unestablished
