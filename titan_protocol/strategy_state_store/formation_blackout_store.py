"""Restart-safe, concurrency-safe per-`(pair, range_start)` formation-time
news-blackout observation store (ADR-035 §2/§14, Amendment 1, Phase 7).

Persists whether `pair_safety.news.blackout_active` was ever observed
`True` at any evaluation cycle within `[range_start, range_end)` for a
given opening range's own formation window -- the same, already-computed
boolean the existing evaluation-time check reads, never reconstructed or
reinterpreted here (Amendment 1's ownership-boundary rejection of
duplicating Market Intelligence's own blackout-window arithmetic).

Design constraints this module exists to satisfy:

- `record_cycle_observation()`/`was_blackout_observed()` are the only two
  public methods. Unlike `OrbQualificationStore.try_consume()` (a single
  atomic gate, deliberately never split into a read/increment pair
  because splitting would reintroduce a race), this fact's write
  contract is a genuinely different shape -- an idempotent,
  unconditional OR-accumulate, written every cycle throughout formation
  and read, without mutation, once at evaluation -- so a read/write
  split here introduces no equivalent race.
- Monotonic: once `(pair, range_start)` is recorded `True`, a later
  `record_cycle_observation(..., False)` for the same key must never
  clear it back to `False`.
- Restart-safe: the in-memory map is loaded from disk exactly once at
  construction and is the sole authority read/written for the rest of
  the process's own lifetime.
- A disk-persist failure inside `record_cycle_observation()` is caught
  and logged here, never allowed to escape -- identical fault-
  containment rationale to `OrbQualificationStore`'s own (an exception
  escaping into `OrbBreakoutStrategy.qualify()` would abort
  `StrategyEngine.evaluate()`/`evaluate_batch()` for every strategy and
  pair in that cycle).
- Corrupt/unreadable persisted state fails closed at construction --
  never silently treated as "nothing observed yet."
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from .config import StrategyStateStoreConfig

_LOGGER = logging.getLogger(__name__)

#: Bumped whenever the on-disk shape changes. Independently versioned
#: from `strategy_state_store.models.SCHEMA_VERSION` -- the two are
#: unrelated persisted formats owned by two different facts.
FORMATION_BLACKOUT_SCHEMA_VERSION = 1


class CorruptFormationBlackoutStateError(Exception):
    """Raised when persisted formation-blackout state exists but cannot
    be trusted (missing keys, wrong types, unknown schema version,
    invalid JSON, and no usable backup either). Callers must fail closed
    on this -- never silently fall back to fresh/empty state, since that
    could silently permit an unsafe `QUALIFIED` result for a range whose
    formation blackout was already observed before a restart."""


@dataclass(frozen=True)
class PersistedFormationBlackoutState:
    """The full, restart-safe formation-blackout observation state."""

    schema_version: int
    entries: Dict[str, bool]


def _safe_log_persist_failure(exc: Exception) -> None:
    """The last line of defense between a persist failure and that
    failure compounding itself: never raises, under any circumstance,
    mirroring `OrbQualificationStore`'s own and this codebase's broader
    `_safe_log_exception()` fault-containment precedent
    (`deployment_windows/start.py`)."""
    try:
        _LOGGER.error("Formation-blackout observation state persist failed", exc_info=exc)
    except Exception:  # noqa: BLE001 -- intentionally unconditional, see docstring
        pass


def _state_to_dict(entries: Dict[str, bool]) -> dict:
    return {"schema_version": FORMATION_BLACKOUT_SCHEMA_VERSION, "entries": entries}


def _dict_to_state(raw: dict) -> PersistedFormationBlackoutState:
    if raw.get("schema_version") != FORMATION_BLACKOUT_SCHEMA_VERSION:
        raise CorruptFormationBlackoutStateError(
            f"persisted formation-blackout state has schema_version={raw.get('schema_version')!r}, "
            f"expected {FORMATION_BLACKOUT_SCHEMA_VERSION!r} -- no migration is defined for this version"
        )
    return PersistedFormationBlackoutState(
        schema_version=raw["schema_version"],
        entries={str(k): bool(v) for k, v in raw["entries"].items()},
    )


class FormationBlackoutStore:
    def __init__(self, config: StrategyStateStoreConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        with self._lock:
            self._entries: Dict[str, bool] = self._load_initial()

    def _load_initial(self) -> Dict[str, bool]:
        path = self._config.state_file
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

        raise CorruptFormationBlackoutStateError(
            f"persisted formation-blackout state at {path} is missing/corrupted and no usable "
            f"backup was found -- refusing to silently treat this as 'nothing observed yet', "
            f"since that could re-permit an unsafe qualification for a range whose formation "
            f"blackout already occurred. Original error: {primary_error!r}"
        ) from primary_error

    def _persist(self) -> None:
        path = self._config.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_bytes(path.read_bytes())
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-formation-blackout-state-", suffix=".json")
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

    def record_cycle_observation(self, pair: str, range_start: datetime, blackout_active: bool) -> None:
        """Idempotent OR-accumulate: `(pair, range_start)` transitions
        from "not observed" to "observed" the first time `blackout_active`
        is `True` for that key, and never transitions back. A cycle that
        does not change the recorded value skips the persist entirely --
        the common case (a range whose formation never sees a blackout)
        therefore never touches disk. A persist failure is caught and
        logged inside this method; the in-memory value already stands
        regardless."""
        key = f"{pair}|{range_start.isoformat()}"
        with self._lock:
            current = self._entries.get(key, False)
            new_value = current or blackout_active
            if new_value == current:
                return
            self._entries[key] = new_value
            try:
                self._persist()
            except Exception as exc:  # noqa: BLE001 -- a write failure must never escape qualify()
                _safe_log_persist_failure(exc)

    def was_blackout_observed(self, pair: str, range_start: datetime) -> bool:
        """`True` if `record_cycle_observation()` has ever recorded a
        `True` blackout for this `(pair, range_start)` key -- `False` for
        a key never observed, exactly matching "nothing has been
        observed yet" as the correct initial state."""
        key = f"{pair}|{range_start.isoformat()}"
        with self._lock:
            return self._entries.get(key, False)


__all__ = [
    "FORMATION_BLACKOUT_SCHEMA_VERSION",
    "CorruptFormationBlackoutStateError",
    "PersistedFormationBlackoutState",
    "FormationBlackoutStore",
]
