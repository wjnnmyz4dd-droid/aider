"""Restart-safe, concurrency-safe per-`(pair, range_start)` ORB
qualification lockout (ADR-035 §18.A item 2, Phase 2 Step 2B).

Design constraints this module exists to satisfy:

- `try_consume()` is the sole public method -- deliberately never split
  into a `get_count()`/`increment()` pair, since that would reintroduce
  exactly the race this design must prevent.
- The in-memory `_entries` dict, loaded from disk exactly once at
  construction, is the sole authority every `try_consume()` call reads
  and increments for the rest of the process's lifetime -- never
  re-read from disk mid-process. A lost write cannot cause a later call
  to under-count and silently re-allow an already-consumed
  `(pair, range_start)`.
- Every persist writes the complete `_entries` dict, never a per-key
  delta -- so a later successful persist for any key durably flushes an
  earlier key's failed increment too, as a side effect.
- A disk-persist failure inside `try_consume()`'s critical section is
  caught and logged here, never allowed to escape: an exception
  escaping into `OrbBreakoutStrategy.qualify()` would abort
  `StrategyEngine.evaluate()`/`evaluate_batch()` for every strategy and
  pair in that cycle, since neither has any exception handling around
  strategy qualification. The in-memory qualification decision stands
  either way (ADR-035 §18.A) -- persisted state must not be "silently
  swallowed" (satisfied here through visible logging), not "the caller
  must be told via a raised exception."
- Corrupt/unreadable persisted state fails closed at construction --
  never silently treated as "nothing consumed yet."
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from typing import Dict

from .config import StrategyStateStoreConfig
from .models import SCHEMA_VERSION, CorruptStateError, PersistedOrbQualificationState

_LOGGER = logging.getLogger(__name__)


def _safe_log_persist_failure(exc: Exception) -> None:
    """The last line of defense between a persist failure and that
    failure compounding itself: never raises, under any circumstance,
    mirroring this codebase's own `_safe_log_exception()` fault-
    containment precedent (`deployment_windows/start.py`)."""
    try:
        _LOGGER.error("ORB qualification state persist failed", exc_info=exc)
    except Exception:  # noqa: BLE001 -- intentionally unconditional, see docstring
        pass


def _state_to_dict(entries: Dict[str, int]) -> dict:
    return {"schema_version": SCHEMA_VERSION, "entries": entries}


def _dict_to_state(raw: dict) -> PersistedOrbQualificationState:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CorruptStateError(
            f"persisted ORB qualification state has schema_version={raw.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION!r} -- no migration is defined for this version"
        )
    return PersistedOrbQualificationState(
        schema_version=raw["schema_version"],
        entries={str(k): int(v) for k, v in raw["entries"].items()},
    )


class OrbQualificationStore:
    def __init__(self, config: StrategyStateStoreConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        with self._lock:
            self._entries: Dict[str, int] = self._load_initial()

    def _load_initial(self) -> Dict[str, int]:
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

        raise CorruptStateError(
            f"persisted ORB qualification state at {path} is missing/corrupted and no usable "
            f"backup was found -- refusing to silently treat this as 'nothing consumed yet', "
            f"since that could re-allow an already-consumed opening range. "
            f"Original error: {primary_error!r}"
        ) from primary_error

    def _persist(self) -> None:
        path = self._config.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_bytes(path.read_bytes())
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-orb-qualification-state-", suffix=".json")
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

    def try_consume(self, pair: str, range_start: datetime, max_allowed: int) -> bool:
        """Atomically: read the in-memory count for `(pair, range_start)`,
        reject if already at `max_allowed`, otherwise increment the
        in-memory count and attempt to persist the complete current
        state. A persist failure is caught and logged inside this
        method -- the in-memory increment already stands regardless.
        The entire sequence executes while holding `self._lock` -- no
        caller can observe an intermediate state."""
        key = f"{pair}|{range_start.isoformat()}"
        with self._lock:
            current = self._entries.get(key, 0)
            if current >= max_allowed:
                return False
            self._entries[key] = current + 1
            try:
                self._persist()
            except Exception as exc:  # noqa: BLE001 -- a write failure must never escape try_consume()
                _safe_log_persist_failure(exc)
            return True


__all__ = ["OrbQualificationStore"]
