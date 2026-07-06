"""Session/day/weekend scheduling for the Paper Trading Runner (Phase 4).

**Not Scanner's session tagging, and never fed into it.** Scanner already
computes which session(s) are active *for a given `ScannerObservation`*
(`scanner.config.SessionWindow`, surfaced on
`ScannerObservation.session.active_sessions`) — that remains Scanner's
sole authority for what a trade candidate "happened during," and
`analytics.attribution.group_by_session` already reads it directly.
`SessionManager` answers a different, Runner-level question: *when should
the paper-trading loop itself reset daily counters, or pause for the
weekend?* — a scheduling concern the trading pipeline itself has no stage
for, exactly as Compliance Engine's `AccountState.daily_drawdown_pct` was
always meant to be supplied by an external, non-pipeline component (see
`account_tracker.py`).

**Why a third, `paper_trading`-owned `SessionWindow`, rather than
importing Scanner's or Compliance Engine's.** Those two packages already
carry two independent, deliberately-undeduplicated copies of this exact
5-field type — each one's own docstring says so explicitly ("mirrors...",
"the same known limitation... already documents"). That is this
codebase's own established precedent for this exact situation: a private,
package-owned config value, not a shared cross-package type. A third
private copy here follows that precedent; reaching into either existing
package's `.config` module would be the actual deviation (and would also
violate `scripts/check_architecture.py`'s "no cross-package private-state
access" rule, since `SessionWindow` lives in `.config`, not `.models`/
`.trace`/`.registry`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Tuple


@dataclass(frozen=True)
class SessionWindow:
    """A named session's daily UTC-of-day window, inclusive start,
    exclusive end. Does not itself handle daylight-saving transitions in
    a venue's local time — the same known limitation `scanner.config.
    SessionWindow`/`compliance_engine.config.SessionWindow` already
    document for their own copies of this type."""

    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int

    def contains(self, hour: int, minute: int) -> bool:
        start = self.start_hour * 60 + self.start_minute
        end = self.end_hour * 60 + self.end_minute
        point = hour * 60 + minute
        if start <= end:
            return start <= point < end
        return point >= start or point < end  # wraps past midnight (e.g. Asian session)


class Session(Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"


@dataclass(frozen=True)
class SessionManagerConfig:
    """Every threshold/window here is a tunable implementation default,
    never architecture (`CLAUDE.md` §7, §3) — the same discipline every
    prior stage's config module already established. Session hours are
    the same UTC placeholder set `scanner.config`/`compliance_engine.
    config` already use as their own Phase 1 defaults."""

    session_windows: Tuple[SessionWindow, ...] = field(
        default_factory=lambda: (
            SessionWindow("SYDNEY", 21, 0, 6, 0),
            SessionWindow("TOKYO", 0, 0, 9, 0),
            SessionWindow("LONDON", 7, 0, 16, 0),
            SessionWindow("NEW_YORK", 12, 0, 21, 0),
        )
    )
    daily_reset_hour_utc: int = 0
    daily_reset_minute_utc: int = 0
    # Weekend: FX markets close Friday evening and reopen Sunday evening
    # (UTC); this is a configurable placeholder default, not a broker-
    # specific guarantee (mirrors ADR-006's own "does not itself handle
    # daylight-saving transitions" caveat).
    weekend_close_weekday: int = 4  # Friday (Monday=0)
    weekend_close_hour_utc: int = 21
    weekend_reopen_weekday: int = 6  # Sunday
    weekend_reopen_hour_utc: int = 21


DEFAULT_CONFIG = SessionManagerConfig()


class SessionManager:
    def __init__(self, config: SessionManagerConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def active_sessions(self, now: datetime) -> Tuple[str, ...]:
        """The Runner's own independently-computed view of which named
        sessions are active at `now` — for scheduling only (see module
        docstring); never a substitute for `ScannerObservation.session`."""
        return tuple(
            window.name
            for window in self.config.session_windows
            if window.contains(now.hour, now.minute)
        )

    def is_weekend(self, now: datetime) -> bool:
        """True from Friday close through Sunday reopen (both UTC,
        configurable) — the window during which a paper-trading loop
        should not expect a live tick feed."""
        close_minutes = self.config.weekend_close_weekday * 24 * 60 + self.config.weekend_close_hour_utc * 60
        reopen_minutes = self.config.weekend_reopen_weekday * 24 * 60 + self.config.weekend_reopen_hour_utc * 60
        point_minutes = now.weekday() * 24 * 60 + now.hour * 60 + now.minute
        if close_minutes <= reopen_minutes:
            return close_minutes <= point_minutes < reopen_minutes
        return point_minutes >= close_minutes or point_minutes < reopen_minutes

    def is_trading_day(self, now: datetime) -> bool:
        return not self.is_weekend(now)

    def trading_day_start(self, now: datetime) -> datetime:
        """The most recent daily-reset boundary at or before `now`."""
        candidate = now.replace(
            hour=self.config.daily_reset_hour_utc,
            minute=self.config.daily_reset_minute_utc,
            second=0,
            microsecond=0,
        )
        if candidate > now:
            candidate -= timedelta(days=1)
        return candidate

    def is_new_trading_day(self, previous_now: datetime, now: datetime) -> bool:
        """Whether a daily-reset boundary was crossed strictly between
        `previous_now` and `now` — used by `AccountTracker` to know when
        to re-baseline the day-start equity reading."""
        return self.trading_day_start(now) > self.trading_day_start(previous_now)


__all__ = ["Session", "SessionWindow", "SessionManagerConfig", "DEFAULT_CONFIG", "SessionManager"]
