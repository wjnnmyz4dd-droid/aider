"""Persistent, restart-surviving deduplication ledger (spec §8).

An append-only, fsync'd JSONL under ``health/`` keyed by ``signal_id`` with its
terminal state. It is the dedup authority: a signal_id present here has been
processed and must never be processed again. Survives process/terminal restart
because it is durable on disk.
"""

from __future__ import annotations

import json

from .atomic import append_line_fsync


class DedupLedger:
    def __init__(self, ledger_path):
        self.path = ledger_path
        self._seen = {}
        self._load()

    def _load(self):
        self._seen = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue          # skip a torn trailing line; never crash
                    sid = rec.get("signal_id")
                    if isinstance(sid, str):
                        self._seen[sid] = rec
        except FileNotFoundError:
            pass

    def is_seen(self, signal_id):
        return signal_id in self._seen

    def get(self, signal_id):
        return self._seen.get(signal_id)

    def record(self, signal_id, state, result_id, processed_iso):
        """Durably record a terminal outcome for ``signal_id`` (idempotent: the
        first terminal record wins; re-records are ignored in memory)."""
        rec = {"signal_id": signal_id, "state": state,
               "result_id": result_id, "processed_timestamp": processed_iso}
        append_line_fsync(self.path, json.dumps(rec, sort_keys=True, separators=(",", ":")))
        self._seen.setdefault(signal_id, rec)
        return rec
