"""Manage-channel filesystem layout (Phase 7B-B). Separate from the ENTER tree."""

from __future__ import annotations

import re
from pathlib import Path

MANAGE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

_SUBDIRS = (
    "manage/outbox/pending", "manage/outbox/claimed", "manage/inbox/results",
    "manage/archive/applied", "manage/archive/rejected", "manage/archive/closed",
    "manage/quarantine", "manage/health",
)


class ManagePaths:
    def __init__(self, root):
        self.root = Path(root).resolve()
        m = self.root / "manage"
        self.pending = m / "outbox" / "pending"
        self.claimed = m / "outbox" / "claimed"
        self.results = m / "inbox" / "results"
        self.archive_applied = m / "archive" / "applied"
        self.archive_rejected = m / "archive" / "rejected"
        self.archive_closed = m / "archive" / "closed"
        self.quarantine = m / "quarantine"
        self.health = m / "health"
        self.ledger = self.health / "ledger.json"        # manager/adapter state
        self.ea_ledger = self.health / "ea_ledger.json"  # EA-side dedup (separate actor)
        self.audit_log = self.health / "manage_audit.jsonl"

    def ensure(self):
        for sub in _SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self


def instruction_name(manage_id):
    return f"{manage_id}.json"


def result_name(manage_id, result_id):
    return f"{manage_id}.{result_id}.json"


def manage_id_from_name(name):
    stem = name.split(".", 1)[0]
    return stem if MANAGE_ID_RE.match(stem) else None
