"""Deterministic freshness & sanity checks for acquired calendars (§5).

Operates on the provider's :class:`RawCalendar` and the injected ``now`` (tz-aware
UTC). Fails closed on: missing/malformed/future/stale SOURCE timestamps and empty
payloads. Event-time validity is checked during normalization. No wall clock here
(``now`` is injected), no networking.

Note: individual EVENT timestamps are legitimately in the future (they are
scheduled events) and are NOT rejected for being future — only the SOURCE/bundle
timestamps are skew/staleness checked.
"""

from __future__ import annotations

from datetime import timezone

from .contract import AcquisitionError, Reason


def _require_utc(dt, reason):
    if dt is None:
        raise AcquisitionError(reason, {"missing": "timestamp"})
    if dt.tzinfo is None or dt.utcoffset() is None:
        # Internally everything must be tz-aware UTC; a naive datetime is a bug/
        # malformed input -> fail closed rather than silently assume a zone.
        raise AcquisitionError(Reason.INVALID_TIMESTAMP, {"naive_datetime": True})
    return dt.astimezone(timezone.utc)


def check_source_freshness(raw_calendar, now, cfg):
    """Validate the acquisition's source/fetch timestamps against ``now``.

    * ``fetched_at`` must be present and not implausibly in the future (clock skew).
    * If the source declares ``source_as_of`` it must be within the max source age
      and not beyond the allowed future skew; a *missing* source_as_of is allowed
      (many free calendars omit it) but recorded honestly by the caller.
    * Fail closed on an empty payload.
    """
    now = _require_utc(now, Reason.MISSING_SOURCE_TIME)
    fetched = _require_utc(raw_calendar.fetched_at, Reason.MISSING_SOURCE_TIME)

    skew = int(cfg.max_clock_skew_sec)
    if (fetched - now).total_seconds() > skew:
        raise AcquisitionError(Reason.FUTURE_SOURCE_TIME,
                               {"fetched_ahead_sec": (fetched - now).total_seconds(),
                                "max_clock_skew_sec": skew})

    if not raw_calendar.events:
        raise AcquisitionError(Reason.EMPTY_PAYLOAD, {"event_count": 0})

    src = raw_calendar.source_as_of
    if src is not None:
        src = _require_utc(src, Reason.INVALID_TIMESTAMP)
        if (src - now).total_seconds() > skew:
            raise AcquisitionError(Reason.FUTURE_SOURCE_TIME,
                                   {"source_ahead_sec": (src - now).total_seconds(),
                                    "max_clock_skew_sec": skew})
        age = (now - src).total_seconds()
        if age > int(cfg.max_source_age_sec):
            raise AcquisitionError(Reason.STALE_SOURCE,
                                   {"source_age_sec": age,
                                    "max_source_age_sec": int(cfg.max_source_age_sec)})
    return True
