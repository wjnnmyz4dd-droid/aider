"""Session strategy profiles (PR-4A) — the ONE authoritative binding of each
supported trading session to the SAME Session Edge ORB methodology.

The four supported sessions are NOT four strategies: they are four *session
instances* of the frozen London ORB methodology, differing only by the session
clock. Nothing here re-implements the strategy — a profile only supplies the
session-timing overrides the frozen engine already consumes
(``session_tz``/``or_start_local_*``/``or_window_minutes``/
``session_end_local_hour``/``friday_no_new_entry_local_hour``).

Single source of truth:
  * IANA timezone + local session-open are REUSED from ``session/model.SESSIONS``
    (never duplicated here).
  * The opening range is ``[session_open, session_open + 60m)`` (half-open).
  * The strategy entry window END is derived from the frozen London relationship
    (spec §3.1 / DEFAULT_CONFIG): OR end + 12 local-clock hours.
  * The Friday no-new-entry cutoff is ``strategy_entry_end - 1 local hour``.

London under this table reproduces the frozen DEFAULT_CONFIG exactly:
  OR 08:00–09:00 Europe/London, entry end 21:00, Friday cutoff 20:00.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import LONDON, NEW_YORK, SESSIONS, SYDNEY, TOKYO

# Shared, frozen methodology constants (same for every session in v1).
OR_DURATION_MIN = 60
ENTRY_WINDOW_HOURS_AFTER_OR = 12          # frozen London relationship (OR end + 12h)
STRATEGY_VARIANT = "swing_orb.session.v1"

# Canonical order used whenever a deterministic session sequence is needed. Config
# ordering must never change outcomes (candidates are independent per session), but a
# stable order keeps audits/tests reproducible.
SUPPORTED_SESSION_IDS = (SYDNEY, TOKYO, LONDON, NEW_YORK)

_DISPLAY_NAMES = {
    SYDNEY: "Sydney", TOKYO: "Tokyo", LONDON: "London", NEW_YORK: "New York",
}


class SessionProfileError(ValueError):
    """Raised when a session profile cannot be constructed safely (fail closed)."""


@dataclass(frozen=True)
class SessionProfile:
    """One session instance of the shared ORB methodology. Timing only; geometry
    (breakout/stop/RR/width) stays in the common strategy config."""

    session_id: str
    display_name: str
    timezone: str                                   # IANA (from session/model.SESSIONS)
    or_start_local_hour: int
    or_start_local_minute: int = 0
    or_window_minutes: int = OR_DURATION_MIN
    entry_window_hours_after_or: int = ENTRY_WINDOW_HOURS_AFTER_OR
    strategy_variant: str = STRATEGY_VARIANT

    @property
    def _or_end_total_minutes(self):
        return (self.or_start_local_hour * 60 + self.or_start_local_minute
                + self.or_window_minutes)

    @property
    def or_end_local_hour(self):
        return self._or_end_total_minutes // 60

    @property
    def or_end_local_minute(self):
        return self._or_end_total_minutes % 60

    @property
    def strategy_entry_end_local_hour(self):
        """Outer entry-authorization boundary = OR end + 12 local hours. v1 profiles
        all land on a whole hour strictly before local midnight; anything else is
        unsupported (fail closed) rather than silently wrapping past midnight."""
        if self.or_end_local_minute != 0:
            raise SessionProfileError(
                f"{self.session_id}: OR end must be on a whole hour in v1")
        end = self.or_end_local_hour + self.entry_window_hours_after_or
        if not (0 < end < 24):
            raise SessionProfileError(
                f"{self.session_id}: strategy entry end {end}:00 must be within the "
                "same local day (cross-midnight entry windows unsupported in v1)")
        return end

    @property
    def friday_no_new_entry_local_hour(self):
        return self.strategy_entry_end_local_hour - 1

    def is_within_strategy_window(self, now):
        """True iff ``now`` falls in this session's [OR start, strategy entry end)
        window in the session's own IANA timezone (DST-aware). This is the STRATEGY
        entry authorization window (SC-2: NOT the coarse market-session close). Fail
        closed on a missing/naive ``now``."""
        if now is None or getattr(now, "tzinfo", None) is None:
            return False
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo(self.timezone))
        minute = local.hour * 60 + local.minute
        start = self.or_start_local_hour * 60 + self.or_start_local_minute
        end = self.strategy_entry_end_local_hour * 60
        return start <= minute < end

    def is_friday_no_new_entry(self, now):
        """True iff ``now`` is AT OR AFTER this session's Friday no-new-entry cutoff
        in the session's own IANA timezone (DST-aware). M12: at/after the cutoff on a
        Friday NO new entry may be authorized; the cutoff is per-session (each derived
        from that session's own clock, so no session can borrow another's cutoff), and
        it never affects open-position MANAGEMENT (owned by the position manager). The
        boundary is hour-granular and uses ``>=``, matching the frozen engine's own
        ``friday_exit`` comparison. Fail closed on a missing/naive ``now`` (block)."""
        if now is None or getattr(now, "tzinfo", None) is None:
            return True
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo(self.timezone))
        return local.weekday() == 4 and local.hour >= self.friday_no_new_entry_local_hour

    def engine_overrides(self):
        """The session-timing config overrides the frozen engine consumes. Geometry
        keys are intentionally absent — they come from the shared strategy config."""
        return {
            "session_id": self.session_id,
            "session_tz": self.timezone,
            "or_start_local_hour": self.or_start_local_hour,
            "or_start_local_minute": self.or_start_local_minute,
            "or_window_minutes": self.or_window_minutes,
            "session_end_local_hour": self.strategy_entry_end_local_hour,
            "friday_no_new_entry_local_hour": self.friday_no_new_entry_local_hour,
        }

    def as_dict(self):
        return {
            "session_id": self.session_id,
            "display_name": self.display_name,
            "timezone": self.timezone,
            "or_start_local": f"{self.or_start_local_hour:02d}:{self.or_start_local_minute:02d}",
            "or_end_local": f"{self.or_end_local_hour:02d}:{self.or_end_local_minute:02d}",
            "strategy_entry_end_local": f"{self.strategy_entry_end_local_hour:02d}:00",
            "friday_no_new_entry_local": f"{self.friday_no_new_entry_local_hour:02d}:00",
            "strategy_variant": self.strategy_variant,
        }


def _build_profile(session_id):
    if session_id not in SESSIONS:
        raise SessionProfileError(f"unknown session: {session_id!r}")
    tz, open_min, _close_min = SESSIONS[session_id]      # REUSE model.SESSIONS (no dup)
    return SessionProfile(
        session_id=session_id, display_name=_DISPLAY_NAMES[session_id],
        timezone=tz, or_start_local_hour=open_min // 60,
        or_start_local_minute=open_min % 60)


# The authoritative profile table (built from session/model.SESSIONS).
PROFILES = {sid: _build_profile(sid) for sid in SUPPORTED_SESSION_IDS}


def profile_for(session_id):
    """Return the SessionProfile for ``session_id`` or raise (fail closed)."""
    p = PROFILES.get(session_id)
    if p is None:
        raise SessionProfileError(f"unsupported session: {session_id!r}")
    return p


def profiles_for(session_ids):
    """Deterministic tuple of profiles for ``session_ids`` in canonical order (so
    config ordering cannot change outcomes). Raises on any unknown session."""
    requested = set(session_ids)
    unknown = requested - set(PROFILES)
    if unknown:
        raise SessionProfileError(f"unsupported session(s): {sorted(unknown)!r}")
    if not requested:
        raise SessionProfileError("no sessions selected")
    return tuple(PROFILES[sid] for sid in SUPPORTED_SESSION_IDS if sid in requested)
