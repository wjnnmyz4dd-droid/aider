"""ForexFactory economic-calendar provider (Phase 9D-R1) — THE network boundary.

This is the ONLY module in Session Edge that performs outbound networking, and it
does so for calendar DATA acquisition only. It never trades, never touches
compliance/risk/positions/bridge/EA. Selected source: ForexFactory's free weekly
JSON calendar — no API key, stable schema, currency-coded events with
previous/forecast (and actual after release).

Safety of the network seam (§13):
  * Host is a FIXED allow-list constant — no arbitrary/caller URL fetching.
  * Bounded connect/read timeout on every request.
  * Redirects are NOT followed to a different host (untrusted-host redirect guard).
  * Response is parsed as inert JSON only (``json.loads``) — never eval/exec.
  * The actual HTTP call is injected (``fetcher``) so tests never touch the network.

Completeness (§10): the weekly feed provides no completeness guarantee, so this
provider reports ``complete=None`` (unestablished) — it never claims completeness
merely because a request succeeded.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .contract import AcquisitionError, RawCalendar, Reason
from .provider import CalendarProvider

# Fixed allow-list — the ONLY hosts/paths this provider may fetch. No caller URL.
_ALLOWED_HOST = "nfs.faireconomy.media"
_ENDPOINTS = {
    "thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "nextweek": "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
}


def _default_fetcher(url, timeout):  # pragma: no cover - real network only
    """Minimal, hardened GET. Bounded timeout; rejects a cross-host redirect."""
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    if urlparse(url).hostname != _ALLOWED_HOST:
        raise AcquisitionError(Reason.SOURCE_ERROR, {"disallowed_host": url})

    class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlparse(newurl).hostname != _ALLOWED_HOST:
                raise AcquisitionError(Reason.SOURCE_ERROR,
                                       {"cross_host_redirect": newurl})
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_NoCrossHostRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "SessionEdge-Calendar/1.0"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                raise AcquisitionError(Reason.SOURCE_ERROR, {"status": resp.status})
            return resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        reason = Reason.TIMEOUT if "timed out" in str(exc).lower() else Reason.SOURCE_ERROR
        raise AcquisitionError(reason, {"error": repr(exc)})


class ForexFactoryCalendarProvider(CalendarProvider):
    """Fetches + shallow-parses the ForexFactory weekly JSON into a RawCalendar.

    ``fetcher(url, timeout) -> str`` is injected for tests; production uses the
    hardened default. ``now_fn`` supplies the tz-aware UTC fetched_at."""

    name = "forexfactory"
    version = "forexfactory.v1"
    trusted = True

    def __init__(self, *, window="thisweek", timeout=12.0, fetcher=None,
                 now_fn=None):
        if window not in _ENDPOINTS:
            raise AcquisitionError(Reason.CONFIG_ERROR, {"window": window})
        self.window = window
        self.timeout = float(timeout)
        self._fetch_url = fetcher or _default_fetcher
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def fetch(self, now=None):
        import json
        url = _ENDPOINTS[self.window]
        try:
            text = self._fetch_url(url, self.timeout)
        except AcquisitionError:
            raise
        except Exception as exc:                       # noqa: BLE001 - fail closed
            raise AcquisitionError(Reason.PROVIDER_UNAVAILABLE, {"error": repr(exc)})
        try:
            rows = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"error": repr(exc)})
        if not isinstance(rows, list):
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD,
                                   {"type": type(rows).__name__})
        return RawCalendar(
            source_name=self.name, source_identifier=f"ff_calendar_{self.window}.json",
            provider_version=self.version, fetched_at=self._now(),
            events=tuple(rows), source_as_of=None,     # weekly feed carries no as_of
            complete=None, trusted=self.trusted)       # completeness unestablished
