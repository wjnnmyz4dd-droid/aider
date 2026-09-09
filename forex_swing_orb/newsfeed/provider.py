"""Calendar acquisition provider interface + non-networking providers.

The narrow provider contract returns a :class:`RawCalendar` (raw source rows +
acquisition metadata). Source-specific parsing stays INSIDE the provider so
``compliance/news.py`` and the normalization layer stay source-agnostic and new
providers can be added later without touching compliance (§2).

This module contains only NON-networking providers (a local-file provider and an
injectable/testing provider). The real network provider is isolated in
``http_provider.py`` so the network boundary is a single, testable seam (§13).
"""

from __future__ import annotations

import abc
import json
from datetime import datetime, timezone
from pathlib import Path

from ..bridge import serialize
from .contract import AcquisitionError, RawCalendar, Reason


def _utc_now():
    return datetime.now(timezone.utc)


class CalendarProvider(abc.ABC):
    """Acquire a raw calendar. Implementations MUST NOT approve/reject trades,
    compute signals, or touch compliance/risk/positions — data only."""

    name = "abstract"
    version = "0"
    trusted = False

    @abc.abstractmethod
    def fetch(self, now):
        """Return a :class:`RawCalendar`. Raise :class:`AcquisitionError` on any
        provider/source failure (never return a partial/fabricated calendar)."""


class StaticFileCalendarProvider(CalendarProvider):
    """Reads a LOCAL raw-calendar JSON file (no networking). Useful offline and for
    an operator who drops a raw source dump for the layer to normalize/verify.

    Expected file shape: ``{"source_as_of": <iso|null>, "complete": <bool|null>,
    "events": [ {raw row}, ... ]}`` or a bare ``[ {raw row}, ... ]`` list."""

    def __init__(self, path, *, source_name="static_file", version="static.v1",
                 trusted=False, now_fn=_utc_now):
        self.path = str(path)
        self.name = source_name
        self.version = version
        self.trusted = bool(trusted)
        self._now = now_fn

    def fetch(self, now=None):
        try:
            text = Path(self.path).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise AcquisitionError(Reason.PROVIDER_UNAVAILABLE, {"path": self.path,
                                                                 "error": repr(exc)})
        try:
            obj = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"error": repr(exc)})

        if isinstance(obj, list):
            rows, source_as_of, complete = obj, None, None
            cov_start = cov_end = None
        elif isinstance(obj, dict):
            rows = obj.get("events")
            source_as_of = serialize.parse_iso(obj.get("source_as_of"))
            complete = obj.get("complete")
            cov_start = serialize.parse_iso(obj.get("coverage_start"))
            cov_end = serialize.parse_iso(obj.get("coverage_end"))
        else:
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"type": type(obj).__name__})
        if not isinstance(rows, list):
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD, {"missing": "events"})

        return RawCalendar(
            source_name=self.name, source_identifier=Path(self.path).name,
            provider_version=self.version, fetched_at=self._now(),
            events=tuple(rows), source_as_of=source_as_of, complete=complete,
            trusted=self.trusted, coverage_start=cov_start, coverage_end=cov_end)


class InjectableCalendarProvider(CalendarProvider):
    """Wraps a caller-supplied ``fetch_fn(now) -> RawCalendar`` (dependency
    injection for tests and for composing a custom acquisition source without
    subclassing). Exceptions from ``fetch_fn`` are surfaced unchanged; an
    :class:`AcquisitionError` propagates, anything else is wrapped as SOURCE_ERROR."""

    def __init__(self, fetch_fn, *, name="injected", version="injected.v1",
                 trusted=False):
        self._fetch = fetch_fn
        self.name = name
        self.version = version
        self.trusted = bool(trusted)

    def fetch(self, now):
        try:
            raw = self._fetch(now)
        except AcquisitionError:
            raise
        except Exception as exc:                      # noqa: BLE001 - fail closed
            raise AcquisitionError(Reason.SOURCE_ERROR, {"error": repr(exc)})
        if not isinstance(raw, RawCalendar):
            raise AcquisitionError(Reason.MALFORMED_PAYLOAD,
                                   {"returned": type(raw).__name__})
        return raw
