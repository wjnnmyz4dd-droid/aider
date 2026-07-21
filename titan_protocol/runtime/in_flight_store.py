"""Restart-safe persistence for `InFlightCommandRegistry`'s minimal
pair-level state (production-readiness hardening, ADR-034 Amendment 9).

Design constraints this module exists to satisfy:

- Persists only the four fields `InFlightCommandRegistry.
  snapshot_for_persistence()` exposes -- correlation_id, pair, state,
  timestamp -- never the original `TradeCommand`. `CommandQueue` itself
  is never persisted (in-memory only, unchanged by this module), so a
  restored entry can only ever be released by its own TTL/timeout, never
  by a late-arriving `ExecutionReport` for a correlation_id `CommandQueue`
  no longer remembers. This is a deliberate scope limit, not an
  oversight -- see ADR-034 Amendment 9 for the full rationale.
- Same atomic-write technique already proven by
  `titan_protocol.compliance_state_store.store.ComplianceStateStore`: a
  temp file is written and fsync'd, then swapped in with `os.replace`
  (atomic on both POSIX and Windows), so a crash mid-write can never
  leave a half-written state file; the previous good file is rotated to
  a `.bak` sibling before every overwrite.
- Unlike compliance state, corruption here is fail-SAFE, not
  fail-closed: `load()` returns an empty tuple (never raises) if the
  primary file and its `.bak` sibling are both missing or unusable.
  Losing this best-effort bookkeeping only means a restart resumes with
  exactly today's behavior (no restart-safety for whatever was mid-flight
  at the moment of the crash) -- never a refusal to start the Bridge, and
  `ComplianceEngine`'s own live position-limit check (fed by real
  `/bridge/positions` reports, entirely independent of this store)
  remains the actual duplicate-position guard regardless of whether this
  file could be read. Refusing to start the whole Bridge over a
  corrupted best-effort optimization file would itself be a worse
  capital-preservation outcome than proceeding with one restart's worth
  of reduced restart-safety.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

from .in_flight_commands import InFlightSnapshotEntry

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class InFlightStoreConfig:
    state_file: Path


def _entry_to_dict(entry: InFlightSnapshotEntry) -> dict:
    return {
        "correlation_id": entry.correlation_id,
        "pair": entry.pair,
        "state": entry.state,
        "timestamp": entry.timestamp.isoformat(),
    }


def _entry_from_dict(raw: dict) -> InFlightSnapshotEntry:
    return InFlightSnapshotEntry(
        pair=str(raw["pair"]),
        correlation_id=str(raw["correlation_id"]),
        state=str(raw["state"]),
        timestamp=datetime.fromisoformat(raw["timestamp"]),
    )


class InFlightCommandStore:
    def __init__(self, config: InFlightStoreConfig) -> None:
        self.config = config

    def load(self) -> Tuple[InFlightSnapshotEntry, ...]:
        """Returns whatever was last saved, or `()` if the file has never
        existed, or if both the primary file and its `.bak` backup are
        missing/corrupted/malformed -- see module docstring for why
        fail-safe (never raising) is the correct choice here, unlike
        `ComplianceStateStore.load_or_bootstrap()`'s fail-closed
        `CorruptStateError`."""
        path = self.config.state_file
        if not path.exists():
            return ()
        try:
            return self._parse(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- any parse failure means "cannot trust this file"
            pass
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            try:
                return self._parse(backup.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 -- backup is also unusable
                pass
        return ()

    def _parse(self, text: str) -> Tuple[InFlightSnapshotEntry, ...]:
        raw = json.loads(text)
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"in-flight state has schema_version={raw.get('schema_version')!r}, expected {SCHEMA_VERSION!r} "
                "-- no migration is defined for this version"
            )
        return tuple(_entry_from_dict(e) for e in raw["entries"])

    def save(self, entries: Iterable[InFlightSnapshotEntry]) -> None:
        """Call once per live cycle with `InFlightCommandRegistry.
        snapshot_for_persistence()` -- always overwrites with the full
        current set (never an incremental patch), so a pair reconcile()
        already dropped this cycle (resolved, abandoned, or expired)
        is simply absent from the next save, and can never be restored
        after a subsequent restart."""
        path = self.config.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_bytes(path.read_bytes())
        payload = {"schema_version": SCHEMA_VERSION, "entries": [_entry_to_dict(e) for e in entries]}
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-in-flight-state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
            raise


__all__ = ["InFlightCommandStore", "InFlightStoreConfig", "SCHEMA_VERSION"]
