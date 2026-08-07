"""Acquisition health/status file (§9) — read-only, atomically written.

Reports whether autonomous acquisition is healthy without ever exposing a
credential. There are no secrets on the calendar config in this phase (the selected
source needs none); this module additionally asserts no credential-shaped key is
ever serialized, as defense in depth. No HTTP/sockets — a plain status file, like
the other Session Edge status surfaces.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from .contract import SCHEMA_VERSION

# Keys that must never appear in a persisted health/status artifact.
_FORBIDDEN = ("password", "secret", "token", "api_key", "apikey", "credential",
              "authorization", "auth")


class HealthState:
    """Mutable in-memory acquisition health, snapshotted atomically to a file."""

    def __init__(self, *, enabled, provider, file_path):
        self.enabled = bool(enabled)
        self.provider = provider
        self.file_path = file_path
        self.last_attempt = None
        self.last_success = None
        self.last_failure = None
        self.last_failure_reason = None
        self.source_as_of = None
        self.bundle_as_of = None
        self.event_count = None
        self.next_refresh = None
        self.completeness = None
        self.healthy = False

    def record_attempt(self, now_iso):
        self.last_attempt = now_iso

    def record_success(self, *, now_iso, bundle, next_refresh_iso):
        self.healthy = True
        self.last_success = now_iso
        self.last_failure_reason = None
        prov = bundle.get("provenance", {}) if isinstance(bundle, dict) else {}
        self.source_as_of = prov.get("source_as_of")
        self.bundle_as_of = bundle.get("as_of")
        self.event_count = prov.get("event_count")
        self.completeness = prov.get("completeness")
        self.next_refresh = next_refresh_iso

    def record_failure(self, *, now_iso, reason, next_refresh_iso):
        self.healthy = False
        self.last_failure = now_iso
        self.last_failure_reason = reason
        self.next_refresh = next_refresh_iso

    def to_dict(self):
        return {
            "kind": "calendar_acquisition_status",
            "schema_version": SCHEMA_VERSION,
            "enabled": self.enabled,
            "provider": self.provider,
            "healthy": self.healthy,
            "last_attempt": self.last_attempt,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_failure_reason": self.last_failure_reason,
            "source_as_of": self.source_as_of,
            "bundle_as_of": self.bundle_as_of,
            "event_count": self.event_count,
            "completeness": self.completeness,
            "next_refresh": self.next_refresh,
            "file_path": self.file_path,
        }


def _assert_no_credentials(status):
    for k in status:
        lk = str(k).lower()
        if any(f in lk for f in _FORBIDDEN):
            raise ValueError(f"refusing to write credential-shaped key: {k!r}")


def write_health(path, status):
    """Atomically write the health dict as canonical JSON (credential-safe)."""
    _assert_no_credentials(status)
    atomic_write_text(path, serialize.canonical_json(status))
    return path
