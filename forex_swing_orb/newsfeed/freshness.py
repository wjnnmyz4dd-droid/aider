"""Deterministic freshness, coverage & effective-as-of policy (Phase 9D-R1-R, F-2).

The core correction: "an HTTP request succeeded now" is NOT "the upstream calendar
information is fresh now." The authoritative ``as_of`` the compliance gate consumes
must be an EFFECTIVE calendar freshness derived from a defensible signal — not the
download time.

Two independent signals are used, in order of strength:
  1. An explicit upstream ``source_as_of`` (generated timestamp), when the source
     provides one (the selected ForexFactory weekly feed does NOT). Staleness and
     future-skew are enforced against it.
  2. A COVERAGE check: the payload's own event span must include ``now`` (i.e. this
     is the calendar for the current period). A calendar for the wrong week fails
     closed. Coverage is derived from the full event set (not one event).

Only when a defensible signal holds is a fresh ``effective_calendar_as_of`` produced.
Otherwise a :class:`AcquisitionError` (FRESHNESS_UNESTABLISHED / COVERAGE_INVALID)
is raised, the last-known-good file is left untouched, and the existing compliance
freshness rule eventually blocks trading. All datetimes are tz-aware UTC; ``now`` is
injected (no wall clock here).
"""

from __future__ import annotations

from datetime import timedelta, timezone

from ..bridge import serialize
from .contract import (COVERAGE_EVENT_SPAN, COVERAGE_SOURCE_DECLARED,
                       AcquisitionError, Reason)


def _require_utc(dt, reason):
    if dt is None:
        raise AcquisitionError(reason, {"missing": "timestamp"})
    if getattr(dt, "tzinfo", None) is None or dt.utcoffset() is None:
        raise AcquisitionError(Reason.INVALID_TIMESTAMP, {"naive_datetime": True})
    return dt.astimezone(timezone.utc)


def check_download_sanity(raw_calendar, now, cfg):
    """Cheap pre-checks on the download itself (NOT a freshness claim): present
    fetched_at, non-empty payload, fetch not implausibly in the future (skew), and
    — if the source declares a generated timestamp — that it is neither future nor
    older than ``max_source_age_sec``."""
    now = _require_utc(now, Reason.MISSING_SOURCE_TIME)
    fetched = _require_utc(raw_calendar.fetched_at, Reason.MISSING_SOURCE_TIME)
    skew = int(cfg.max_clock_skew_sec)
    if (fetched - now).total_seconds() > skew:
        raise AcquisitionError(Reason.FUTURE_SOURCE_TIME,
                               {"fetched_ahead_sec": (fetched - now).total_seconds()})
    if not raw_calendar.events:
        raise AcquisitionError(Reason.EMPTY_PAYLOAD, {"event_count": 0})

    src = raw_calendar.source_as_of
    if src is not None:
        src = _require_utc(src, Reason.INVALID_TIMESTAMP)
        if (src - now).total_seconds() > skew:
            raise AcquisitionError(Reason.FUTURE_SOURCE_TIME,
                                   {"source_ahead_sec": (src - now).total_seconds()})
        if (now - src).total_seconds() > int(cfg.max_source_age_sec):
            raise AcquisitionError(Reason.STALE_SOURCE,
                                   {"source_age_sec": (now - src).total_seconds(),
                                    "max_source_age_sec": int(cfg.max_source_age_sec)})
    return True


def compute_coverage(normalized_events, raw_calendar):
    """Derive the interval the calendar is intended to cover. Prefer a source-declared
    coverage; otherwise derive it from the FULL event span, snapped outward to whole
    UTC days (robust to edge events, never certainty from a single event).

    Returns ``(coverage_start, coverage_end, basis)`` (tz-aware UTC)."""
    if raw_calendar.coverage_start is not None and raw_calendar.coverage_end is not None:
        cs = _require_utc(raw_calendar.coverage_start, Reason.INVALID_TIMESTAMP)
        ce = _require_utc(raw_calendar.coverage_end, Reason.INVALID_TIMESTAMP)
        if ce < cs:
            raise AcquisitionError(Reason.COVERAGE_INVALID, {"end_before_start": True})
        return cs, ce, COVERAGE_SOURCE_DECLARED

    times = [serialize.parse_iso(e["event_timestamp"]) for e in normalized_events]
    times = [t for t in times if t is not None]
    if not times:
        raise AcquisitionError(Reason.FRESHNESS_UNESTABLISHED, {"no_event_times": True})
    lo, hi = min(times), max(times)
    coverage_start = lo.replace(hour=0, minute=0, second=0, microsecond=0)
    coverage_end = hi.replace(hour=23, minute=59, second=59, microsecond=0)
    return coverage_start, coverage_end, COVERAGE_EVENT_SPAN


def establish_effective_as_of(raw_calendar, normalized_events, now, cfg):
    """Return ``(effective_calendar_as_of, coverage_start, coverage_end, basis,
    coverage_verified)``.

    The calendar must demonstrably cover ``now`` (fail closed on the wrong week).
    ``effective_calendar_as_of`` is the source-declared generated timestamp when
    available, else the fetch time — but ONLY once coverage proves the payload is the
    calendar for the current period. This is what makes the written ``as_of`` a
    validated-freshness signal rather than a bare download timestamp (F-2)."""
    now = _require_utc(now, Reason.MISSING_SOURCE_TIME)
    coverage_start, coverage_end, basis = compute_coverage(normalized_events, raw_calendar)
    grace = timedelta(seconds=int(cfg.coverage_grace_sec))
    if not (coverage_start - grace <= now <= coverage_end + grace):
        raise AcquisitionError(Reason.COVERAGE_INVALID, {
            "now": serialize.iso_utc(now),
            "coverage_start": serialize.iso_utc(coverage_start),
            "coverage_end": serialize.iso_utc(coverage_end),
            "basis": basis})

    if raw_calendar.source_as_of is not None:
        effective = _require_utc(raw_calendar.source_as_of, Reason.INVALID_TIMESTAMP)
    else:
        # No upstream generated timestamp: coverage is the defensible signal, so the
        # validated-current fetch time is the effective freshness. (Not a bare
        # download stamp — it is only reached AFTER coverage proves currency.)
        effective = _require_utc(raw_calendar.fetched_at, Reason.MISSING_SOURCE_TIME)
    return effective, coverage_start, coverage_end, basis, True
