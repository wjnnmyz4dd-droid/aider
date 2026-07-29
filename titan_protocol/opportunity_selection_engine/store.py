"""Restart-safe, concurrency-safe, winner-only opportunity-window
persistence (ADR-037 §9, as corrected by Amendment 1 -- Persistence
Semantics Correction, Accepted).

Design constraints this module exists to satisfy (mirroring
`strategy_state_store/store.py::OrbQualificationStore`'s exact,
already-Accepted design precedent):

- `decide_once()` is the sole public method -- deliberately never split
  into a `get()`/`set()` pair, since that would reintroduce exactly the
  race this design must prevent.
- The in-memory `_entries` dict, loaded from disk exactly once at
  construction, is the sole authority every `decide_once()` call reads
  and writes for the rest of the process's lifetime -- never re-read
  from disk mid-process.
- **Only a genuine, single winning pair is ever written to this store**
  (Amendment 1 §2): a "no winner this cycle" outcome (an empty candidate
  set, or an unresolved tie) creates no durable entry at all -- the key
  remains absent, and absence means exactly one thing, "no durable
  winner has yet been established for this opportunity window," never
  "this opportunity window has permanently concluded with no winner."
  No terminal-window boundary is invented or required by this design.
- Once a genuine winner is durably established for a `range_start`, it
  is immutable: the entire check-then-persist sequence executes under
  one lock, so two genuinely concurrent calls for the same `range_start`
  can never independently select and persist two different winners --
  whichever acquires the lock first resolves the decision; the second
  call re-checks the (possibly now-populated) key before computing
  anything of its own.
- A disk-persist failure inside `decide_once()` is caught and logged
  here, never allowed to escape -- the in-memory decision (a genuine
  winner, once selected) stands regardless, mirroring
  `OrbQualificationStore`'s own established fault-containment
  precedent.
- Corrupt/unreadable persisted state fails closed at construction --
  never silently treated as "no winner has been established for any
  window."
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

from titan_protocol.strategy_engine.models import SessionName

from .models import (
    SCHEMA_VERSION,
    CorruptOpportunityWinnerStateError,
    OpportunityCandidate,
    PersistedOpportunityWinnerState,
)
from .selection import select_winner

_LOGGER = logging.getLogger("titan_protocol.opportunity_selection_engine")


def _safe_log_persist_failure(exc: Exception) -> None:
    """The last line of defense between a persist failure and that
    failure compounding itself: never raises, under any circumstance,
    mirroring `OrbQualificationStore`'s own `_safe_log_persist_failure()`
    fault-containment precedent."""
    try:
        _LOGGER.error("opportunity winner state persist failed", exc_info=exc)
    except Exception:  # noqa: BLE001 -- intentionally unconditional, see docstring
        pass


def _safe_log_stale_window(range_start: datetime, now: datetime) -> None:
    try:
        _LOGGER.warning(
            "stale_window_encountered",
            extra={"range_start": range_start.isoformat(), "now": now.isoformat()},
        )
    except Exception:  # noqa: BLE001 -- logging must never fail closed-in-the-wrong-direction
        pass


def _state_to_dict(entries: Dict[str, dict]) -> dict:
    return {"schema_version": SCHEMA_VERSION, "entries": entries}


def _dict_to_state(raw: dict) -> PersistedOpportunityWinnerState:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CorruptOpportunityWinnerStateError(
            f"persisted opportunity winner state has schema_version={raw.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION!r} -- no migration is defined for this version"
        )
    entries = raw["entries"]
    for key, value in entries.items():
        if not isinstance(value, dict) or "pair" not in value or not isinstance(value["pair"], str):
            raise CorruptOpportunityWinnerStateError(
                f"persisted opportunity winner state entry {key!r} is malformed: {value!r}"
            )
    return PersistedOpportunityWinnerState(
        schema_version=raw["schema_version"],
        entries={str(k): dict(v) for k, v in entries.items()},
    )


class OpportunityWinnerStore:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file
        self._lock = threading.Lock()
        with self._lock:
            self._entries: Dict[str, dict] = self._load_initial()

    def _load_initial(self) -> Dict[str, dict]:
        path = self._state_file
        if not path.exists():
            return {}
        primary_error: Exception
        try:
            return _dict_to_state(json.loads(path.read_text(encoding="utf-8"))).entries
        except Exception as exc:  # noqa: BLE001 -- any of these means "cannot trust this file"
            primary_error = exc

        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            try:
                return _dict_to_state(json.loads(backup.read_text(encoding="utf-8"))).entries
            except Exception:  # noqa: BLE001 -- backup is also unusable
                pass

        raise CorruptOpportunityWinnerStateError(
            f"persisted opportunity winner state at {path} is missing/corrupted and no usable "
            f"backup was found -- refusing to silently treat this as 'no winner established for "
            f"any window,' since that could allow a second, different winner to be selected for "
            f"a range_start that already has a durable winner on disk. Original error: {primary_error!r}"
        ) from primary_error

    def _persist(self) -> None:
        path = self._state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_bytes(path.read_bytes())
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-opportunity-winner-state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_state_to_dict(self._entries), handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise

    def decide_once(
        self,
        range_start: datetime,
        session_name: SessionName,
        candidates: Tuple[OpportunityCandidate, ...],
        tie_tolerance: float,
        duration_minutes: int,
        now: datetime,
    ) -> Optional[str]:
        """Atomically, under one lock:

        1. Stale-window defense-in-depth (ADR-037 §12): if this
           `range_start`'s window should already be closed, log
           distinctly and return `None` without touching the store at
           all -- a should-never-happen guard, since the caller only
           ever presents a `range_start` Evidence Engine just computed
           as currently relevant this cycle.
        2. If `range_start.isoformat()` is already a key (a genuine
           winner was durably decided on a prior call): return the
           persisted pair unchanged, without even constructing
           `candidates` into `select_winner()`.
        3. Else: call `select_winner(candidates, tie_tolerance)`. A
           genuine single winner is persisted and returned. A "no
           winner" result (zero candidates or an unresolved tie)
           persists nothing and returns `None` for this cycle only --
           the key remains absent, so any later cycle recomputes fully
           fresh.
        """
        if range_start + timedelta(minutes=duration_minutes) < now:
            _safe_log_stale_window(range_start, now)
            return None

        key = range_start.isoformat()
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                return existing["pair"]

            outcome = select_winner(candidates, tie_tolerance)
            if outcome.winner is None:
                # No durable entry created -- the key remains absent,
                # and the cycle is fully re-computable on every later
                # call (Amendment 1 §2).
                return None

            self._entries[key] = {
                "session_name": session_name.value,
                "pair": outcome.winner,
                "decided_at": now.isoformat(),
            }
            try:
                self._persist()
            except Exception as exc:  # noqa: BLE001 -- a write failure must never escape decide_once()
                _safe_log_persist_failure(exc)
            return outcome.winner


__all__ = ["OpportunityWinnerStore"]
