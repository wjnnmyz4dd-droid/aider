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
ACK_NAME_RE = re.compile(r"^[0-9a-f]{16}\.[0-9a-f]{16}\.ack\.json$")
SIGNAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")

_SUBDIRS = (
    "outbox/pending",
    "outbox/claimed",
    "inbox/results",
    "inbox/acks",
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
        self.acks = self.root / "inbox" / "acks"
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


def ack_name(signal_id, ack_id):
    return f"{signal_id}.{ack_id}.ack.json"


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


def safe_read_text(path, root, max_bytes):
    """Read a file's text with the TOCTOU window reduced (F-3): open without
    following symlinks where supported, then validate the OPEN descriptor (not
    just the path) is a regular file under the root and within the size cap.

    Returns (ok, text, reason) where reason in {"", "unsafe", "too_large", "io"}.
    """
    p = Path(path)
    try:
        real_root = Path(root).resolve()
    except OSError:
        return False, None, "unsafe"
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)    # refuse a symlink at the final component
    flags |= getattr(os, "O_BINARY", 0)      # Windows: no newline translation
    try:
        fd = os.open(str(p), flags)
    except OSError:
        return False, None, "unsafe"
    try:
        st = os.fstat(fd)                     # stat the DESCRIPTOR, not the path
        import stat as _stat
        if not _stat.S_ISREG(st.st_mode):
            return False, None, "unsafe"
        # containment check on the opened path
        try:
            Path(os.path.realpath(str(p))).relative_to(real_root)
        except ValueError:
            return False, None, "unsafe"
        if st.st_size > max_bytes:
            return False, None, "too_large"
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            return False, None, "too_large"
        return True, data.decode("utf-8"), ""
    except (OSError, UnicodeDecodeError):
        return False, None, "io"
    finally:
        os.close(fd)
