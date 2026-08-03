"""Persisted, restart-safe ORB qualification-lockout state (ADR-035
§18.A item 2, Phase 2 Step 2B).

A thin, caller-owned persistence record -- not a new strategy model.
`entries` maps a `(pair, range_start)` key (encoded as
`f"{pair}|{range_start.isoformat()}"`, since JSON object keys must be
strings) to the number of qualifications already consumed for that
opening range."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

#: Bumped whenever the on-disk shape changes. `store.py` refuses to load
#: a file whose `schema_version` it does not explicitly know how to
#: read (fail closed on ambiguous persisted state) rather than guessing.
SCHEMA_VERSION = 1


class CorruptStateError(Exception):
    """Raised when persisted ORB qualification state exists but cannot
    be trusted (missing keys, wrong types, unknown schema version,
    invalid JSON, and no usable backup either). Callers must fail closed
    on this -- never silently fall back to fresh/empty state, since that
    would silently re-allow an already-consumed `(pair, range_start)`."""


@dataclass(frozen=True)
class PersistedOrbQualificationState:
    """The full, restart-safe ORB qualification-lockout state."""

    schema_version: int
    entries: Dict[str, int]


__all__ = ["SCHEMA_VERSION", "CorruptStateError", "PersistedOrbQualificationState"]
