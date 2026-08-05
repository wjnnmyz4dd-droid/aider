"""Canonical trading-session model (Phase 9A) — the ONE owner of session/overlap
time-window logic for Session Edge.

Everything that needs session awareness (runtime config, producer scanning,
compliance session gate, news presentation, advisory context, manager reporting,
dashboards) consumes THIS module. It computes no strategy signal, places no trade,
and adds no networking. Deterministic: identical (model, now) -> identical
snapshot + snapshot_id. Time is always injected and timezone-aware.

FOREX-only, FTMO 2-Step Swing, DEMO-only context.
"""

from __future__ import annotations

from .model import (SESSIONS, OVERLAPS, SESSION_IDS, OVERLAP_IDS, OverlapMode,
                    SessionModel, SessionReason, active_sessions, active_overlaps,
                    next_session, next_overlap, session_countdown, session_snapshot,
                    eligibility, snapshot_id)
from .capability import (StrategyCapability, LONDON_ORB_CAPABILITY,
                         strategy_session_support, StrategySessionPolicy)

__all__ = [
    "SESSIONS", "OVERLAPS", "SESSION_IDS", "OVERLAP_IDS", "OverlapMode",
    "SessionModel", "SessionReason", "active_sessions", "active_overlaps",
    "next_session", "next_overlap", "session_countdown", "session_snapshot",
    "eligibility", "snapshot_id", "StrategyCapability", "LONDON_ORB_CAPABILITY",
    "strategy_session_support", "StrategySessionPolicy",
]
