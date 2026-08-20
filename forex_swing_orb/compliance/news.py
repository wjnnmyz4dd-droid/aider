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

# Impact vocabulary the authority recognizes. HIGH blocks; the KNOWN-non-blocking
# set is recognized-but-harmless (MEDIUM/LOW/none categories). These mirror the
# newsfeed normalizer's vocabulary so a normalized bundle classifies exactly. Any
# OTHER non-empty impact on a RELEVANT, in-window event is UNKNOWN and fails closed
# (M6): the gate is the authority and never treats an unrecognized impact as safe.
_HIGH = frozenset({"HIGH", "H", "3", "3.0", "RED", "CRITICAL"})
_KNOWN_NONBLOCKING = frozenset({
    "MEDIUM", "MED", "M", "2", "2.0", "ORANGE",
    "LOW", "L", "1", "1.0", "YELLOW", "GRAY", "GREY",
    "NONE", "N", "0", "HOLIDAY", "NON-ECONOMIC",
})


def _reject(codes, evidence):
    return GateVerdict(Stage.NEWS, False, tuple(codes), evidence)


def _is_currency_code(value):
    """True iff ``value`` is a well-formed 3-letter currency code — enough to
    PROVE an event is (ir)relevant to a pair. A malformed currency cannot prove
    irrelevance, so it is treated as unestablishable (fail closed, M7 CASE C)."""
    if not isinstance(value, str):
        return False
    c = value.strip().upper()
    return len(c) == 3 and c.isalpha()


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

    # M-3: bundle-level verification is a property of the BUNDLE and is proven
    # BEFORE any event filtering. When verification is required, an unverified /
    # unproven bundle can NEVER pass — regardless of zero, irrelevant, or
    # out-of-window events, or a malformed candidate symbol. Missing/false/wrongly
    # typed `verified` is NOT trusted: no truthiness — a real boolean True or the
    # canonical "VERIFIED" token is required (mirrors the per-event vocabulary,
    # without the ``1 == True`` numeric leak). Freshness above and impact below
    # remain independent fail-closed gates.
    if cfg.require_verified:
        v = news_bundle.get("verified")
        if not (v is True or v == "VERIFIED"):
            return _reject([ReasonCode.NEWS_SOURCE_UNVERIFIED],
                           {"verified": v, "bundle_verification": "required"})

    symbol = candidate.get("symbol")
    pre = int(cfg.pre_lockout_min)
    post = int(cfg.post_lockout_min)

    hits = []
    seen = {}                       # event_id -> (timestamp, impact) for conflict detection
    for ev in events:
        # RELEVANCE FIRST (M7): establish whether this event can affect THIS pair
        # before requiring its other fields, so a malformed but provably UNRELATED
        # event never blocks a safe pair — while any event whose relevance cannot be
        # established fails closed.
        if not isinstance(ev, dict):
            # no establishable currency -> cannot prove irrelevance (M7 CASE C)
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE], {"malformed": "event"})
        cur = ev.get("currency")
        if not _is_currency_code(cur):
            # currency/relevance unestablishable -> fail closed (M7 CASE C)
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE],
                           {"malformed_currency": ev.get("event_id")})
        if not mapping.pair_blocked_by_currency(symbol, cur):
            continue                # provably unrelated -> skip (M7 CASE B), even if malformed

        # RELEVANT event: its safety fields MUST be establishable or fail closed
        # (M7 CASE A/F). event_id/impact/timestamp are all safety-relevant here.
        eid = ev.get("event_id")
        imp = ev.get("impact")
        ts = ev.get("event_timestamp")
        if eid is None or imp is None or ts is None:
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE],
                           {"malformed_event_id": eid, "currency": str(cur).upper()})
        sig = (ts, str(imp).upper())
        if eid in seen and seen[eid] != sig:
            return _reject([ReasonCode.NEWS_DATA_CONFLICT], {"event_id": eid})
        seen[eid] = sig

        et = serialize.parse_iso(ts)
        if et is None:
            return _reject([ReasonCode.NEWS_DATA_UNAVAILABLE],
                           {"malformed_timestamp": eid})

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

        # IMPACT CLASSIFICATION (M6): for a relevant, in-window, verified event the
        # impact must be a KNOWN value. HIGH blocks; MEDIUM/LOW/none are harmless; an
        # UNKNOWN/unrecognized impact cannot be established as safe -> fail closed.
        imp_norm = str(imp).strip().upper()
        if imp_norm in _HIGH:
            hits.append({
                "event_id": eid,
                "currency": str(cur).upper(),
                "delta_min": round(delta_min, 3),
                "resume_at": serialize.iso_utc(_add_min(et, post)),
            })
        elif imp_norm in _KNOWN_NONBLOCKING:
            continue                # recognized non-market-moving -> does not block
        else:
            return _reject([ReasonCode.NEWS_IMPACT_UNKNOWN, ReasonCode.UNKNOWN_STATE],
                           {"event_id": eid, "currency": str(cur).upper(),
                            "impact": str(imp)})

    if hits:
        # deterministic latest resume time drives auto-resume + dashboard
        resume_times = sorted(h["resume_at"] for h in hits)
        return _reject(
            [ReasonCode.INTERNAL_NEWS_LOCKOUT, ReasonCode.PAIR_BLOCKED],
            {"hits": hits, "lockout_expires_at": resume_times[-1],
             "pre_lockout_min": pre, "post_lockout_min": post},
        )
    return GateVerdict(Stage.NEWS, True, (), {"hits": [], "lockout_expires_at": None})


def _add_min(dt, minutes):
    from datetime import timedelta
    return dt + timedelta(minutes=minutes)
