"""Data models for the Opportunity Selection Engine (ADR-037, Amendment 1).

A thin, caller-owned selection/persistence record set -- not a new
strategy model and not a re-derivation of anything Evidence Engine or
Strategy Engine already computed. `OpportunityCandidate` carries only
the three fields the selection contract (ADR-037 §6) actually consumes;
it deliberately does not carry `confidence`, spread, or liquidity, since
none of them are ranking inputs (ADR-037 §6's own explicit non-decision).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from titan_protocol.strategy_engine.models import SessionName, TradeIntent

#: Bumped whenever the on-disk shape changes. `store.py` refuses to load
#: a file whose `schema_version` it does not explicitly know how to
#: read (fail closed on ambiguous persisted state) rather than guessing.
SCHEMA_VERSION = 1


class CorruptOpportunityWinnerStateError(Exception):
    """Raised when persisted opportunity-winner state exists but cannot
    be trusted (missing keys, wrong types, unknown schema version,
    invalid JSON, and no usable backup either). Callers must fail closed
    on this -- never silently fall back to "no winner established," since
    that could allow a second, different winner to be selected for a
    `range_start` that already has a durable winner on disk. A distinct
    exception type from `strategy_state_store.CorruptStateError` --
    mirroring this codebase's own established precedent that each
    persisted-state concern owns its own exception type (e.g.
    `FormationBlackoutStore`'s own `CorruptFormationBlackoutStateError`,
    distinct from `OrbQualificationStore`'s `CorruptStateError` even
    though both already live in the same `strategy_state_store`
    package)."""


@dataclass(frozen=True)
class OpportunityCandidate:
    """One pair's already-qualified opportunity for a given session
    window -- carries only what the selection contract (ADR-037 §6)
    consumes: `score` (the sole ranking input) and `trade_intent`
    (carried through for the eventual back-half command). Never
    `confidence`, spread, or liquidity -- none of them are ranking
    criteria under this ADR's closed policy decision."""

    pair: str
    score: float
    trade_intent: TradeIntent


@dataclass(frozen=True)
class SessionWindowIdentity:
    """`range_start` alone is the opportunity-window identity (ADR-037
    §8); `session_name` is carried through as a descriptive field only,
    never part of any key."""

    session_name: SessionName
    range_start: datetime


@dataclass(frozen=True)
class SelectionOutcome:
    """The pure result of `select_winner()` (ADR-037 §6) -- `winner` is
    `None` for both "zero candidates" and "unresolved tie" cases;
    `reason` distinguishes them for observability."""

    winner: Optional[str]
    reason: str


@dataclass(frozen=True)
class PersistedOpportunityWinnerState:
    """The full, restart-safe opportunity-winner state (ADR-037 §9, as
    corrected by Amendment 1). `entries` maps a `range_start` key
    (encoded via `.isoformat()`, since JSON object keys must be strings)
    to that window's durably-established winner value. Only a genuine
    winner is ever a key in `entries` -- a "no winner this cycle" result
    (zero candidates or an unresolved tie) never creates an entry at all
    (Amendment 1 §2)."""

    schema_version: int
    entries: Dict[str, dict]


__all__ = [
    "SCHEMA_VERSION",
    "CorruptOpportunityWinnerStateError",
    "OpportunityCandidate",
    "SessionWindowIdentity",
    "SelectionOutcome",
    "PersistedOpportunityWinnerState",
]
