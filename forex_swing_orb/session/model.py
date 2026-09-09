"""Canonical session/overlap model + deterministic helpers (Phase 9A).

Sessions are defined by their LOCAL market clock in an IANA timezone, so DST is
handled by the zone (no fixed-offset approximation). All computation uses the
injected, timezone-aware ``now``; wrap-around windows (open>close) are supported;
helpers return the FULL active set, never just the first.

Window sources: LONDON is anchored to the frozen strategy's own session basis
(``run_dir/code/signal_engine.py`` DEFAULT_CONFIG: session_tz=Europe/London,
or_start_local_hour=8); the other three use standard FX local session hours. These
supersede the earlier fixed-UTC approximation to gain DST correctness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..bridge import serialize

# canonical session ids
SYDNEY, TOKYO, LONDON, NEW_YORK = "SYDNEY", "TOKYO", "LONDON", "NEW_YORK"
SESSION_IDS = (SYDNEY, TOKYO, LONDON, NEW_YORK)

# canonical overlap ids -> (member_a, member_b)
SYDNEY_TOKYO, TOKYO_LONDON, LONDON_NEW_YORK = "SYDNEY_TOKYO", "TOKYO_LONDON", "LONDON_NEW_YORK"
OVERLAP_IDS = (SYDNEY_TOKYO, TOKYO_LONDON, LONDON_NEW_YORK)
OVERLAPS = {
    SYDNEY_TOKYO: (SYDNEY, TOKYO),
    TOKYO_LONDON: (TOKYO, LONDON),
    LONDON_NEW_YORK: (LONDON, NEW_YORK),
}

# session -> (iana_tz, open_local_minute, close_local_minute); wrap if open>close.
SESSIONS = {
    SYDNEY:   ("Australia/Sydney", 7 * 60, 16 * 60),   # 07:00–16:00 local
    TOKYO:    ("Asia/Tokyo",       9 * 60, 18 * 60),   # 09:00–18:00 local (no DST)
    LONDON:   ("Europe/London",    8 * 60, 17 * 60),   # 08:00–17:00 local (anchored to strategy)
    NEW_YORK: ("America/New_York", 8 * 60, 17 * 60),   # 08:00–17:00 local
}


class OverlapMode:
    ALLOW = "ALLOW"       # enabled sessions trade individually; enabled overlaps also trade
    REQUIRE = "REQUIRE"   # eligible ONLY during an enabled active overlap
    DISABLE = "DISABLE"   # overlaps grant no special eligibility; session logic only
    ALL = (ALLOW, REQUIRE, DISABLE)


class SessionReason:
    SESSION_ELIGIBLE = "SESSION_ELIGIBLE"
    SESSION_NOT_ENABLED = "SESSION_NOT_ENABLED"
    OVERLAP_NOT_ENABLED = "OVERLAP_NOT_ENABLED"
    OVERLAP_REQUIRED = "OVERLAP_REQUIRED"
    OUTSIDE_CONFIGURED_SESSION = "OUTSIDE_CONFIGURED_SESSION"
    STRATEGY_SESSION_UNSUPPORTED = "STRATEGY_SESSION_UNSUPPORTED"
    STRATEGY_OVERLAP_UNSUPPORTED = "STRATEGY_OVERLAP_UNSUPPORTED"
    SESSION_CONFIG_INVALID = "SESSION_CONFIG_INVALID"
    SESSION_CONTEXT_STALE = "SESSION_CONTEXT_STALE"
    FRIDAY_CLOSED = "FRIDAY_CLOSED"
    SUNDAY_CLOSED = "SUNDAY_CLOSED"


class SessionConfigError(ValueError):
    """Raised on an invalid canonical session configuration (fail closed)."""


@dataclass(frozen=True)
class SessionModel:
    """The ONE canonical, validated session configuration."""
    enabled_sessions: tuple = ()
    enabled_overlaps: tuple = ()
    overlap_mode: str = OverlapMode.ALLOW
    session_timezone_basis: str = "LOCAL_IANA"     # sessions computed in each IANA zone
    friday_close_policy: int = None                # UTC minute-of-day cutoff (Fri) or None
    sunday_open_policy: int = None                 # UTC minute-of-day reopen (Sun) or None
    session_priority: tuple = SESSION_IDS          # primary-session precedence, high->low
    strategy_session_policy: str = "FAIL_CLOSED"   # FAIL_CLOSED | REPORT_ONLY
    weekend_isoweekdays: tuple = (6, 7)

    def validate(self):
        """Fail closed on unknown ids, empty selection, or invalid combos.
        Returns self on success; raises SessionConfigError otherwise."""
        for s in self.enabled_sessions:
            if s not in SESSIONS:
                raise SessionConfigError(f"unknown session: {s!r}")
        for o in self.enabled_overlaps:
            if o not in OVERLAPS:
                raise SessionConfigError(f"unknown overlap: {o!r}")
        if self.overlap_mode not in OverlapMode.ALL:
            raise SessionConfigError(f"invalid overlap_mode: {self.overlap_mode!r}")
        if self.strategy_session_policy not in ("FAIL_CLOSED", "REPORT_ONLY"):
            raise SessionConfigError(f"invalid strategy_session_policy: {self.strategy_session_policy!r}")
        for s in self.session_priority:
            if s not in SESSIONS:
                raise SessionConfigError(f"unknown session in priority: {s!r}")
        # empty sessions only valid when REQUIRE + at least one enabled overlap
        if not self.enabled_sessions:
            if not (self.overlap_mode == OverlapMode.REQUIRE and self.enabled_overlaps):
                raise SessionConfigError(
                    "empty enabled_sessions requires overlap_mode=REQUIRE with >=1 enabled overlap")
        # REQUIRE with no enabled overlaps can never be eligible -> invalid
        if self.overlap_mode == OverlapMode.REQUIRE and not self.enabled_overlaps:
            raise SessionConfigError("overlap_mode=REQUIRE needs >=1 enabled overlap")
        # an enabled overlap whose members are not enabled is contradictory under ALLOW/DISABLE
        if self.overlap_mode in (OverlapMode.ALLOW, OverlapMode.DISABLE):
            for o in self.enabled_overlaps:
                a, b = OVERLAPS[o]
                if a not in self.enabled_sessions or b not in self.enabled_sessions:
                    raise SessionConfigError(
                        f"overlap {o} enabled but member session(s) not enabled")
        return self

    def digest(self):
        payload = serialize.canonical_json({
            "enabled_sessions": sorted(self.enabled_sessions),
            "enabled_overlaps": sorted(self.enabled_overlaps),
            "overlap_mode": self.overlap_mode,
            "session_timezone_basis": self.session_timezone_basis,
            "friday_close_policy": self.friday_close_policy,
            "sunday_open_policy": self.sunday_open_policy,
            "session_priority": list(self.session_priority),
            "strategy_session_policy": self.strategy_session_policy,
        })
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# time helpers (deterministic; tz-aware; DST via IANA zones)
# --------------------------------------------------------------------------- #
def _local_minute(now, tz_name):
    local = now.astimezone(ZoneInfo(tz_name))
    return local.hour * 60 + local.minute


def _in_window(minute, open_min, close_min):
    if open_min == close_min:
        return False
    if open_min < close_min:
        return open_min <= minute < close_min
    return minute >= open_min or minute < close_min        # wrap past local midnight


def _session_active(session_id, now):
    tz, o, c = SESSIONS[session_id]
    return _in_window(_local_minute(now, tz), o, c)


def active_sessions(model, now):
    """All ENABLED sessions whose local window contains ``now`` (sorted)."""
    if now is None or now.tzinfo is None:
        return ()
    return tuple(sorted(s for s in model.enabled_sessions if _session_active(s, now)))


def active_overlaps(model, now):
    """All ENABLED overlaps whose BOTH member windows contain ``now`` (sorted)."""
    if now is None or now.tzinfo is None:
        return ()
    out = []
    for o in model.enabled_overlaps:
        a, b = OVERLAPS[o]
        if _session_active(a, now) and _session_active(b, now):
            out.append(o)
    return tuple(sorted(out))


def _next_open_utc(session_id, now):
    """Earliest local-open of ``session_id`` strictly after ``now`` (tz-aware)."""
    tz, o, _c = SESSIONS[session_id]
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    for day in range(0, 3):                                 # today .. +2 (covers wrap/DST)
        d = (local + timedelta(days=day)).date()
        cand_local = datetime(d.year, d.month, d.day, o // 60, o % 60, tzinfo=zone)
        cand = cand_local.astimezone(timezone.utc)
        if cand > now:
            return cand
    return None


def next_session(model, now):
    """(session_id, open_utc) of the next enabled session to open after ``now``."""
    best = None
    for s in model.enabled_sessions:
        nxt = _next_open_utc(s, now)
        if nxt is not None and (best is None or nxt < best[1]):
            best = (s, nxt)
    return best


def next_overlap(model, now):
    """(overlap_id, start_utc) of the next enabled overlap window after ``now``.
    Scans minute-resolution over the next 48h (deterministic, bounded)."""
    if not model.enabled_overlaps:
        return None
    for step in range(1, 48 * 60 + 1):
        t = now + timedelta(minutes=step)
        for o in model.enabled_overlaps:
            a, b = OVERLAPS[o]
            if _session_active(a, t) and _session_active(b, t):
                # only report a NEW window (not already active at now)
                a0, b0 = OVERLAPS[o]
                if not (_session_active(a0, now) and _session_active(b0, now)):
                    return (o, t.replace(second=0, microsecond=0))
    return None


def session_countdown(model, now):
    """Seconds until the next session/overlap transition (open of the next enabled
    session), or None. Deterministic."""
    nxt = next_session(model, now)
    if nxt is None:
        return None
    return int((nxt[1] - now).total_seconds())


def _primary(model, active):
    for s in model.session_priority:
        if s in active:
            return s
    return active[0] if active else None


def eligibility(model, now, capability=None, max_age_sec=None, context_age_sec=None):
    """Deterministic scanning eligibility for ``now`` under ``model`` (+ optional
    strategy ``capability``). Returns a dict {eligible, reason, primary_session,
    active_sessions, active_overlaps}. Fail closed on stale context / friday-sunday
    policy / disabled selection / unsupported strategy session."""
    from .capability import strategy_session_support
    act_s = active_sessions(model, now)
    act_o = active_overlaps(model, now)
    primary = _primary(model, act_s)
    base = {"eligible": False, "reason": SessionReason.OUTSIDE_CONFIGURED_SESSION,
            "primary_session": primary, "active_sessions": list(act_s),
            "active_overlaps": list(act_o)}

    if context_age_sec is not None and max_age_sec is not None and context_age_sec > max_age_sec:
        base["reason"] = SessionReason.SESSION_CONTEXT_STALE
        return base

    wd = now.isoweekday()
    m = now.hour * 60 + now.minute
    if model.friday_close_policy is not None and wd == 5 and m >= model.friday_close_policy:
        base["reason"] = SessionReason.FRIDAY_CLOSED
        return base
    if model.sunday_open_policy is not None and wd == 7 and m < model.sunday_open_policy:
        base["reason"] = SessionReason.SUNDAY_CLOSED
        return base

    if model.overlap_mode == OverlapMode.REQUIRE:
        if not act_o:
            base["reason"] = (SessionReason.OVERLAP_REQUIRED if model.enabled_overlaps
                              else SessionReason.OVERLAP_NOT_ENABLED)
            return base
        eligible_via = ("overlap", act_o[0])
    else:
        if act_s:
            eligible_via = ("session", primary)
        elif model.overlap_mode == OverlapMode.ALLOW and act_o:
            eligible_via = ("overlap", act_o[0])
        else:
            base["reason"] = SessionReason.OUTSIDE_CONFIGURED_SESSION
            return base

    # strategy support (fail closed unless policy is REPORT_ONLY)
    kind, ident = eligible_via
    supported, sreason = strategy_session_support(capability, kind, ident, act_s, act_o)
    if not supported and model.strategy_session_policy == "FAIL_CLOSED":
        base["reason"] = sreason
        return base
    base.update({"eligible": True, "reason": SessionReason.SESSION_ELIGIBLE,
                 "eligible_via": {"kind": kind, "id": ident},
                 "strategy_supported": supported,
                 "strategy_support_reason": None if supported else sreason})
    return base


def session_snapshot(model, now, capability=None, max_age_sec=None, context_age_sec=None):
    """Full deterministic session snapshot for audit/status/advisory/dashboard."""
    act_s = active_sessions(model, now)
    act_o = active_overlaps(model, now)
    nxt_s = next_session(model, now)
    nxt_o = next_overlap(model, now)
    elig = eligibility(model, now, capability, max_age_sec, context_age_sec)
    snap = {
        "kind": "session_snapshot",
        "source_timestamp": serialize.iso_utc(now) if now is not None else None,
        "config_version": model.digest(),
        "enabled_sessions": list(model.enabled_sessions),
        "enabled_overlaps": list(model.enabled_overlaps),
        "overlap_mode": model.overlap_mode,
        "active_sessions": list(act_s),
        "active_overlaps": list(act_o),
        "primary_session": elig["primary_session"],
        "next_session": (nxt_s[0] if nxt_s else None),
        "next_session_at": (serialize.iso_utc(nxt_s[1]) if nxt_s else None),
        "next_overlap": (nxt_o[0] if nxt_o else None),
        "next_overlap_at": (serialize.iso_utc(nxt_o[1]) if nxt_o else None),
        "seconds_until_next_transition": session_countdown(model, now),
        "eligible": elig["eligible"],
        "rejection_reason": None if elig["eligible"] else elig["reason"],
        "eligibility_reason": elig["reason"],
        "strategy_supported": elig.get("strategy_supported"),
        "strategy_support_reason": elig.get("strategy_support_reason"),
    }
    snap["snapshot_id"] = snapshot_id(snap)
    return snap


def snapshot_id(snap):
    """Content-addressed 16-hex id over the snapshot (excluding the id itself)."""
    body = {k: v for k, v in snap.items() if k != "snapshot_id"}
    return hashlib.sha256(serialize.canonical_json(body).encode("utf-8")).hexdigest()[:16]
