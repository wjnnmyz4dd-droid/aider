"""Deterministic bridge audit log (spec §Auditing).

Every bridge action appends one structured JSONL line under ``health/``. No silent
failures: producer writes, claims, results, quarantines, and reconciliations all
emit an audit record. Timestamps are inputs, so audit output is deterministic.
"""

from __future__ import annotations

import json

from .atomic import append_line_fsync


class AuditLog:
    def __init__(self, audit_path):
        self.path = audit_path

    def emit(self, timestamp_iso, action, outcome, reason_code="OK",
             signal_id=None, detail=None):
        rec = {
            "timestamp": timestamp_iso,
            "action": action,
            "outcome": outcome,
            "reason_code": reason_code,
            "signal_id": signal_id,
            "detail": detail or {},
        }
        append_line_fsync(self.path, json.dumps(rec, sort_keys=True, separators=(",", ":")))
        return rec

    def read_all(self):
        out = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if raw:
                        out.append(json.loads(raw))
        except FileNotFoundError:
            pass
        return out
