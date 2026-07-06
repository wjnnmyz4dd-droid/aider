"""Session facts (ADR-002 §5).

Session windows are expressed in UTC-of-day terms (see `config.py`'s
`SessionWindow` docstring) — this module does not itself handle
daylight-saving transitions in a venue's local time; a naive (non-timezone
-aware) `session_time` is a `quality.py` failure mode (§9's "clock/session
ambiguity"), not something this module silently guesses through.

`session_time` is normalized to UTC before its hour/minute are read, so
any valid timezone-aware datetime representing a given instant — not only
one already expressed in UTC — resolves to the same `SessionState` (ADR-002
§4 requires only "timezone-aware," not specifically UTC; §2's Purity
Principle requires the same instant to always classify identically
regardless of which equivalent tz representation the caller happens to
supply).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .config import ScannerConfig, SessionWindow
from .models import SessionState


def _window_minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _is_active(now_minutes: int, window: SessionWindow) -> bool:
    start = _window_minutes(window.start_hour, window.start_minute)
    end = _window_minutes(window.end_hour, window.end_minute)
    if start == end:
        return False
    if start < end:
        return start <= now_minutes < end
    # Wraps past midnight (e.g. SYDNEY 21:00 -> 06:00).
    return now_minutes >= start or now_minutes < end


def _window_position(now_minutes: int, window: SessionWindow) -> float:
    start = _window_minutes(window.start_hour, window.start_minute)
    end = _window_minutes(window.end_hour, window.end_minute)
    span = (end - start) % (24 * 60)
    if span == 0:
        span = 24 * 60
    elapsed = (now_minutes - start) % (24 * 60)
    return elapsed / span


def compute_session(session_time: datetime, config: ScannerConfig) -> SessionState:
    if session_time.tzinfo is None:
        return SessionState(active_sessions=(), window_position=None)

    utc_time = session_time.astimezone(timezone.utc)
    now_minutes = _window_minutes(utc_time.hour, utc_time.minute)
    active: Sequence[SessionWindow] = [
        w for w in config.session_windows if _is_active(now_minutes, w)
    ]

    if not active:
        return SessionState(active_sessions=(), window_position=None)

    return SessionState(
        active_sessions=tuple(w.name for w in active),
        window_position=_window_position(now_minutes, active[0]),
    )
