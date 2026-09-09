"""Deterministic append-only compliance audit log (Phase 5C).

Mirrors the bridge audit discipline and REUSES ``bridge.atomic.append_line_fsync``
(atomic, fsync'd JSONL). Records are canonical (``bridge.serialize.canonical_json``):
identical inputs -> identical bytes -> identical ``decision_id``.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import append_line_fsync


class ComplianceAuditLog:
    def __init__(self, audit_path):
        self.path = audit_path

    def emit(self, record):
        """Append one canonical JSONL line for a compliance decision record."""
        append_line_fsync(self.path, serialize.canonical_json(record))
        return record

    def read_all(self):
        out = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    ok, obj = serialize.loads(line)
                    if ok:
                        out.append(obj)
        except FileNotFoundError:
            return []
        return out
