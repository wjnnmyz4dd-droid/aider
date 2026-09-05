"""Acquisition health/status file (Phase 9D-R1-R, F-6) — read-only, atomic.

Reports a single operational ``status`` an operator can act on:

  HEALTHY | PROVIDER_FAILURE | SOURCE_STALE | SOURCE_FRESHNESS_UNESTABLISHED |
  FILE_WRITE_FAILURE | SERVICE_STALE

SERVICE_STALE (the service is not running / hung) cannot be self-reported by a dead
process; it is derived EXTERNALLY from ``last_attempt``/``next_refresh`` via
:func:`derive_service_status` — the exact rule is embedded in the file as
``service_stale_rule``. Never exposes credentials (asserted before every write).
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from .contract import (HEALTH_FILE_WRITE_FAILURE, HEALTH_FRESHNESS_UNESTABLISHED,
                       HEALTH_HEALTHY, HEALTH_PROVIDER_FAILURE, HEALTH_SERVICE_STALE,
                       HEALTH_SOURCE_STALE, SCHEMA_VERSION, Reason, sanitize_detail)

_FORBIDDEN = ("password", "secret", "token", "api_key", "apikey", "credential",
              "authorization", "auth")

# acquisition failure reason -> operational status
_REASON_STATUS = {
    Reason.STALE_SOURCE: HEALTH_SOURCE_STALE,
    Reason.FRESHNESS_UNESTABLISHED: HEALTH_FRESHNESS_UNESTABLISHED,
    Reason.COVERAGE_INVALID: HEALTH_FRESHNESS_UNESTABLISHED,
    Reason.WRITE_FAILED: HEALTH_FILE_WRITE_FAILURE,
}


class HealthState:
    def __init__(self, *, enabled, provider, file_path, refresh_sec):
        self.enabled = bool(enabled)
        self.provider = provider
        self.file_path = file_path
        self.refresh_sec = int(refresh_sec)
        self.status = HEALTH_PROVIDER_FAILURE if enabled else HEALTH_HEALTHY
        self.healthy = False
        self.last_attempt = None
        self.last_success = None
        self.last_failure = None
        self.last_failure_reason = None
        self.last_failure_detail = None      # sanitized structured detail (F/E-observability)
        self.fetched_at = None
        self.source_as_of = None
        self.effective_calendar_as_of = None
        self.coverage_start = None
        self.coverage_end = None
        self.coverage_verified = None
        self.content_hash = None
        self.last_content_change = None
        self.event_count = None
        self.high_event_count = None
        self.next_refresh = None
        # Observational single-owner acquisition state (ACQUIRED / STALE_RECOVERED /
        # ... ) set by the service at startup. A SEPARATE dimension from `status`,
        # `healthy`, and the externally-derived SERVICE_STALE liveness -- never merged.
        self.acquisition_owner = None

    def record_attempt(self, now_iso):
        self.last_attempt = now_iso

    def record_success(self, *, now_iso, bundle, next_refresh_iso):
        prov = bundle.get("provenance", {}) if isinstance(bundle, dict) else {}
        self.healthy = True
        self.status = HEALTH_HEALTHY
        self.last_success = now_iso
        self.last_failure_reason = None
        self.last_failure_detail = None                  # cleared on recovery
        self.fetched_at = prov.get("fetched_at")
        self.source_as_of = prov.get("source_as_of")
        self.effective_calendar_as_of = prov.get("effective_calendar_as_of")
        self.coverage_start = prov.get("coverage_start")
        self.coverage_end = prov.get("coverage_end")
        self.coverage_verified = prov.get("coverage_verified")
        self.event_count = prov.get("event_count")
        self.high_event_count = prov.get("high_event_count")
        new_hash = prov.get("content_hash")
        if new_hash != self.content_hash:            # first sight or genuine change
            self.last_content_change = now_iso
        self.content_hash = new_hash
        self.next_refresh = next_refresh_iso

    def record_failure(self, *, now_iso, reason, next_refresh_iso, detail=None):
        self.healthy = False
        self.status = _REASON_STATUS.get(reason, HEALTH_PROVIDER_FAILURE)
        self.last_failure = now_iso
        self.last_failure_reason = reason
        # Sanitized structured detail (http_status / errno / winerror / exception
        # class ...) so the exact external condition is no longer collapsed into the
        # bare reason code. None when the failure carried no detail.
        self.last_failure_detail = sanitize_detail(detail) if detail else None
        self.next_refresh = next_refresh_iso

    def to_dict(self):
        return {
            "kind": "calendar_acquisition_status",
            "schema_version": SCHEMA_VERSION,
            "enabled": self.enabled,
            "provider": self.provider,
            "status": self.status,
            "healthy": self.healthy,
            "last_attempt": self.last_attempt,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_failure_reason": self.last_failure_reason,
            "last_failure_detail": self.last_failure_detail,
            "fetched_at": self.fetched_at,
            "source_as_of": self.source_as_of,
            "effective_calendar_as_of": self.effective_calendar_as_of,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "coverage_verified": self.coverage_verified,
            "content_hash": self.content_hash,
            "last_content_change": self.last_content_change,
            "event_count": self.event_count,
            "high_event_count": self.high_event_count,
            "next_refresh": self.next_refresh,
            "acquisition_owner": self.acquisition_owner,
            "file_path": self.file_path,
            "refresh_sec": self.refresh_sec,
            "service_stale_rule": (
                "external monitor: SERVICE_STALE if (now - last_attempt) > "
                "2 * refresh_sec"),
        }


def derive_service_status(status_dict, now):
    """External liveness check (a live process cannot report its own death). Returns
    SERVICE_STALE if the last attempt is older than 2x refresh_sec, else the file's
    own status. ``now`` is tz-aware UTC (injected)."""
    last = serialize.parse_iso(status_dict.get("last_attempt"))
    refresh = int(status_dict.get("refresh_sec") or 0)
    if last is None:
        return HEALTH_SERVICE_STALE
    if refresh > 0 and (now - last).total_seconds() > 2 * refresh:
        return HEALTH_SERVICE_STALE
    return status_dict.get("status")


def _assert_no_credentials(status):
    for k in status:
        if any(f in str(k).lower() for f in _FORBIDDEN):
            raise ValueError(f"refusing to write credential-shaped key: {k!r}")


def write_health(path, status):
    _assert_no_credentials(status)
    atomic_write_text(path, serialize.canonical_json(status))
    return path
