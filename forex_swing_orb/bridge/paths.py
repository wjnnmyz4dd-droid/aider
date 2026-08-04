"""Bridge directory layout and filesystem-safety helpers (spec §6, §11).

All bridge state lives beneath a single configurable ``bridge_root`` on one
filesystem so every cross-directory rename is atomic. No path outside the root is
ever touched; symlinks and path-escape are refused.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# signal_id is a 16-hex content hash (strategy spec §8); instruction basenames are
# therefore exactly this and nothing else is accepted from pending/claimed.
INSTRUCTION_NAME_RE = re.compile(r"^[0-9a-f]{16}\.json$")
RESULT_NAME_RE = re.compile(r"^[0-9a-f]{16}\.[0-9a-f]{16}\.json$")
SIGNAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")

_SUBDIRS = (
    "outbox/pending",
    "outbox/claimed",
    "inbox/results",
    "archive/accepted",
    "archive/rejected",
    "quarantine",
    "health",
)


class BridgePaths:
    """Resolved paths for one ``bridge_root``."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.pending = self.root / "outbox" / "pending"
        self.claimed = self.root / "outbox" / "claimed"
        self.results = self.root / "inbox" / "results"
        self.archive_accepted = self.root / "archive" / "accepted"
        self.archive_rejected = self.root / "archive" / "rejected"
        self.quarantine = self.root / "quarantine"
        self.health = self.root / "health"
        self.dedup_ledger = self.health / "dedup.jsonl"
        self.audit_log = self.health / "audit.jsonl"

    def ensure(self):
        """Create the full directory tree with the narrowest permissions (0700)."""
        for sub in _SUBDIRS:
            d = self.root / sub
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self


def instruction_name(signal_id):
    return f"{signal_id}.json"


def result_name(signal_id, result_id):
    return f"{signal_id}.{result_id}.json"


def signal_id_from_instruction_name(name):
    return name[:-5] if INSTRUCTION_NAME_RE.match(name) else None


def is_safe_regular_file(path, root):
    """True iff ``path`` is a real regular file strictly under ``root`` and is not
    a symlink and contains no path-escape (spec §11)."""
    p = Path(path)
    try:
        if p.is_symlink():
            return False
        real = p.resolve()
        root_real = Path(root).resolve()
        real.relative_to(root_real)          # raises if escaping the root
        return real.is_file()
    except (OSError, ValueError):
        return False
