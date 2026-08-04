"""Shared Memory Layer (ONE memory system for all agents).

Filesystem-backed, stdlib-only, no networking. Two tiers:

  * raw/    append-only IMMUTABLE records (jsonl). Never rewritten in place.
  * derived/ versioned summaries keyed by (kind, subject) with a version counter.

Every record has a deterministic content-addressed id, an explicit source
provenance, and a timestamp. Reads go through one query interface. Memory is
advisory: it informs research/reporting and NEVER silently changes live rules.

The audit trail REUSES the bridge's single audit contract
(``forex_swing_orb.bridge.audit.AuditLog``) — no separate audit format.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import append_line_fsync, atomic_write_text
from ..bridge.audit import AuditLog

# Structured record kinds (the one shared taxonomy).
RECORD_KINDS = frozenset({
    "market_context", "agent_assessment", "strategy_decision", "rejected_setup",
    "generated_signal", "execution_outcome", "pnl", "news_condition",
    "liquidity_observation", "risk_decision", "critic_objection",
    "lesson", "model_prompt_version", "shadow_report",
})

RAW_SCHEMA_VERSION = 1
DERIVED_SCHEMA_VERSION = 1


class MemoryError(ValueError):
    pass


class MemoryStore:
    """The single shared memory store. Constructed once and injected into agents;
    there is no per-agent memory."""

    def __init__(self, root, retention_max_raw=1_000_000):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.derived_dir = self.root / "derived"
        self.index_path = self.root / "raw_index.jsonl"
        self.audit = AuditLog(self.root / "memory_audit.jsonl")
        self.retention_max_raw = retention_max_raw
        for d in (self.raw_dir, self.derived_dir):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)

    # -- immutable raw records ---------------------------------------------
    def _raw_id(self, kind, subject, content, source, timestamp):
        payload = serialize.canonical_json(
            {"kind": kind, "subject": subject, "content": content,
             "source": source, "timestamp": timestamp})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def write_raw(self, kind, subject, content, source, timestamp,
                  correlation_id=None):
        """Append one immutable raw record. Idempotent on content: the same
        content maps to the same id and is written at most once."""
        if kind not in RECORD_KINDS:
            raise MemoryError(f"unknown record kind: {kind}")
        if not source:
            raise MemoryError("source provenance is required")
        rid = self._raw_id(kind, subject, content, source, timestamp)
        path = self.raw_dir / f"{rid}.json"
        if path.exists():
            return rid                                    # immutable: never rewrite
        record = {
            "raw_schema_version": RAW_SCHEMA_VERSION,
            "id": rid,
            "kind": kind,
            "subject": subject,
            "content": content,
            "source": source,               # provenance (required)
            "timestamp": timestamp,
            "correlation_id": correlation_id,
        }
        atomic_write_text(path, serialize.canonical_json(record))
        append_line_fsync(self.index_path, serialize.canonical_json(
            {"id": rid, "kind": kind, "subject": subject,
             "timestamp": timestamp, "correlation_id": correlation_id}))
        self.audit.emit(timestamp or "", "memory_write", "RAW",
                        signal_id=rid, detail={"kind": kind, "subject": subject,
                                               "source": source})
        return rid

    def get_raw(self, rid):
        path = self.raw_dir / f"{rid}.json"
        if not path.exists():
            return None
        ok, rec = serialize.loads(path.read_text())
        return rec if ok else None

    # -- versioned derived summaries ---------------------------------------
    def _derived_key(self, kind, subject):
        return hashlib.sha256(
            serialize.canonical_json([kind, subject]).encode("utf-8")).hexdigest()[:16]

    def write_derived(self, kind, subject, summary, source, timestamp):
        """Write a NEW version of a derived summary (never mutates prior ones)."""
        key = self._derived_key(kind, subject)
        existing = self._derived_versions(key)
        version = (max((v["version"] for v in existing), default=0)) + 1
        record = {
            "derived_schema_version": DERIVED_SCHEMA_VERSION,
            "key": key,
            "kind": kind,
            "subject": subject,
            "version": version,
            "summary": summary,
            "source": source,
            "timestamp": timestamp,
        }
        path = self.derived_dir / f"{key}.v{version}.json"
        atomic_write_text(path, serialize.canonical_json(record))
        self.audit.emit(timestamp or "", "memory_write", "DERIVED",
                        signal_id=key, detail={"kind": kind, "version": version})
        return key, version

    def _derived_versions(self, key):
        out = []
        for p in sorted(self.derived_dir.glob(f"{key}.v*.json")):
            ok, rec = serialize.loads(p.read_text())
            if ok:
                out.append(rec)
        return out

    def latest_derived(self, kind, subject):
        versions = self._derived_versions(self._derived_key(kind, subject))
        return max(versions, key=lambda r: r["version"]) if versions else None

    # -- one query interface -----------------------------------------------
    def query(self, kind=None, subject=None, correlation_id=None, limit=1000):
        """Filter raw records via the index (cheap) then load matches."""
        out = []
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return out
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                idx = json.loads(raw)
            except ValueError:
                continue
            if kind and idx.get("kind") != kind:
                continue
            if subject and idx.get("subject") != subject:
                continue
            if correlation_id and idx.get("correlation_id") != correlation_id:
                continue
            rec = self.get_raw(idx["id"])
            if rec is not None:
                out.append(rec)
            if len(out) >= limit:
                break
        return out

    # -- retention (bounded; never deletes below the audit trail) ----------
    def retention_status(self):
        count = sum(1 for _ in self.raw_dir.glob("*.json"))
        return {"raw_records": count, "max": self.retention_max_raw,
                "over": max(0, count - self.retention_max_raw)}
