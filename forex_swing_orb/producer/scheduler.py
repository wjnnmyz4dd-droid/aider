"""Deterministic closed-bar scheduling (Phase 7A).

Pure time math (no wall clock, no sleep here). The service wrapper uses these to
decide *when* the next required bar closes; the runner uses ``last_closed_open``
to detect a new bar and avoid evaluating the same bar twice.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from .contract import tf_minutes


def _floor_to(now, minutes):
    epoch_min = int(now.timestamp() // 60)
    floored = (epoch_min // minutes) * minutes
    from datetime import datetime
    return datetime.fromtimestamp(floored * 60, tz=timezone.utc)


def last_closed_open(now, timeframe):
    """Open time of the most recently CLOSED bar for ``timeframe`` at ``now``."""
    m = tf_minutes(timeframe)
    close = _floor_to(now, m)              # most recent m-boundary <= now == a close
    return close - timedelta(minutes=m)


def next_bar_close(now, timeframe):
    """Wall-clock time of the next bar close after ``now`` (for service sleep)."""
    m = tf_minutes(timeframe)
    floored = _floor_to(now, m)
    return floored + timedelta(minutes=m) if floored <= now else floored


def is_new_bar(last_processed_iso, now, timeframe, parse_iso):
    """True iff a new closed bar exists beyond ``last_processed_iso``."""
    lco = last_closed_open(now, timeframe)
    if last_processed_iso is None:
        return True, lco
    prev = parse_iso(last_processed_iso)
    return (lco > prev), lco
