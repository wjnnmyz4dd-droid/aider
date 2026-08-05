"""Session-aware news PRESENTATION annotation (Phase 9A) — read-only overlay.

This does NOT block trades and does NOT re-implement the news algorithm. The
authoritative high-impact currency news safety rule stays in
``compliance/news.py`` (unchanged): all relevant currency events still block new
entries per the internal lockout window regardless of session. This helper only
ANNOTATES which events are session-relevant and whether a lockout intersects the
next eligible trading window, for advisory context and dashboards.
"""

from __future__ import annotations

from datetime import timedelta

from ..bridge import serialize
from ..compliance import mapping
from ..session import model as sm

_HIGH = frozenset({"HIGH", "H", "3"})


def annotate_news(news_bundle, symbol, session_model, now, *,
                  pre_min=15, post_min=15):
    """Return normalized session-news annotation fields. Never blocks anything."""
    snap_active = sm.active_sessions(session_model, now)
    snap_overlaps = sm.active_overlaps(session_model, now)
    nxt = sm.next_session(session_model, now)
    next_eligible = nxt[0] if nxt else None
    next_at = nxt[1] if nxt else None

    events = (news_bundle or {}).get("events", []) if isinstance(news_bundle, dict) else []
    annotated = []
    lockout_intersects = False
    for ev in events:
        if not isinstance(ev, dict):
            continue
        cur = ev.get("currency")
        relevant = mapping.pair_blocked_by_currency(symbol, cur) if cur else False
        et = serialize.parse_iso(ev.get("event_timestamp"))
        high = str(ev.get("impact", "")).upper() in _HIGH
        # does this event's lockout window overlap the NEXT eligible session open?
        intersects = False
        if relevant and high and et is not None and next_at is not None:
            lo, hi = et - timedelta(minutes=pre_min), et + timedelta(minutes=post_min)
            intersects = lo <= next_at <= hi
            lockout_intersects = lockout_intersects or intersects
        annotated.append({
            "event_id": ev.get("event_id"), "currency": cur,
            "impact": ev.get("impact"),
            "session_relevant_pair": relevant,       # affects the CURRENT symbol
            "lockout_intersects_next_eligible_session": intersects,
        })
    return {
        "active_sessions": list(snap_active),
        "active_overlaps": list(snap_overlaps),
        "next_eligible_session": next_eligible,
        "next_eligible_session_at": serialize.iso_utc(next_at) if next_at else None,
        "event_session_relevance": annotated,
        "lockout_intersects_eligible_window": lockout_intersects,
    }
