"""Deterministic news gate (Phase 5C).

Autonomous and deterministic: trading suspends and resumes purely as a function
of ``now`` versus each event's lockout window. There is NO manual-disable input.
The engine SHALL NOT fetch news; it consumes an injected, normalized NewsBundle.

A HIGH-impact scheduled event for currency C locks out every pair for which C is
the base or quote, for the window ``[t - pre, t + post]`` (default 15/15 min,
configurable). Auto-resume is implicit: once ``now`` passes ``t + post`` the
event no longer matches and the pair trades again.

Supported scheduled event categories (informational; the gate keys off the
``impact`` field, not the name): central-bank decisions (FOMC, ECB, BOE, BOJ,
RBA, RBNZ, BOC, SNB), CPI, PPI, GDP, PMI, NFP, Employment, Inflation, Retail
Sales, and high-impact speeches.
"""

from __future__ import annotations

from ..bridge import serialize
from . import mapping
from .contract import GateVerdict, ReasonCode, Stage

_HIGH = frozenset({"HIGH", "H", "3"})


def _reject(codes, evidence):
    return GateVerdict(Stage.NEWS, False, tuple(codes), evidence)


def gate_news(candidate, news_bundle, cfg, now):
    """Deterministic authority gate. Fails closed on missing/stale/unverified/
    malformed news; blocks on any active HIGH-impact lockout for the pair."""
    if now is None:
        return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE, ReasonCode.UNKNOWN_STATE],
                       {"missing": "now"})
    if not isinstance(news_bundle, dict):
        return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE], {"missing": "news_bundle"})
    events = news_bundle.get("events")
    if not isinstance(events, list):
        return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE], {"missing": "news_bundle.events"})

    # staleness (bundle age is deterministic input)
    as_of = serialize.parse_iso(news_bundle.get("as_of"))
    max_age = int(cfg.max_age_sec)
    if as_of is None:
        return _reject([ReasonCode.NEWS_DATA_STALE], {"missing": "news_bundle.as_of"})
    age = (now - as_of).total_seconds()
    if age > max_age or age < -max_age:
        return _reject([ReasonCode.NEWS_DATA_STALE],
                       {"age_sec": age, "max_age_sec": max_age})

    symbol = candidate.get("symbol")
    pre = int(cfg.pre_lockout_min)
    post = int(cfg.post_lockout_min)

    hits = []
    seen = {}                       # event_id -> (timestamp, impact) for conflict detection
    for ev in events:
        if not isinstance(ev, dict):
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE], {"malformed": "event"})
        eid = ev.get("event_id")
        cur = ev.get("currency")
        imp = ev.get("impact")
        ts = ev.get("event_timestamp")
        if eid is None or cur is None or imp is None or ts is None:
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE],
                           {"malformed_event_id": eid})
        sig = (ts, str(imp).upper())
        if eid in seen and seen[eid] != sig:
            return _reject([ReasonCode.NEWS_CONFLICTING_RECORDS], {"event_id": eid})
        seen[eid] = sig

        et = serialize.parse_iso(ts)
        if et is None:
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE],
                           {"malformed_timestamp": eid})

        # only currencies relevant to THIS pair can affect the decision
        if not mapping.pair_blocked_by_currency(symbol, cur):
            continue
        delta_min = (et - now).total_seconds() / 60.0
        in_window = (-post) <= delta_min <= pre
        if not in_window:
            continue

        # verification enforced ONLY for in-window relevant events (fail closed)
        if cfg.require_verified:
            vstate = ev.get("verification_state", news_bundle.get("verified"))
            if vstate not in ("VERIFIED", True):
                return _reject([ReasonCode.NEWS_SOURCE_UNVERIFIED],
                               {"event_id": eid, "currency": str(cur).upper()})

        if str(imp).upper() in _HIGH:
            resume_at = serialize.iso_utc(et) if post == 0 else None
            hits.append({
                "event_id": eid,
                "currency": str(cur).upper(),
                "delta_min": round(delta_min, 3),
                "resume_at": serialize.iso_utc(_add_min(et, post)),
            })

    if hits:
        # deterministic latest resume time drives auto-resume + dashboard
        resume_times = sorted(h["resume_at"] for h in hits)
        return _reject(
            [ReasonCode.NEWS_LOCKOUT, ReasonCode.PAIR_BLOCKED],
            {"hits": hits, "lockout_expires_at": resume_times[-1],
             "pre_lockout_min": pre, "post_lockout_min": post},
        )
    return GateVerdict(Stage.NEWS, True, (), {"hits": [], "lockout_expires_at": None})


def _add_min(dt, minutes):
    from datetime import timedelta
    return dt + timedelta(minutes=minutes)
