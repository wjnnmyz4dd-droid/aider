"""Atomic filesystem primitives (spec §5). Filesystem-only; no networking.

Write: temp file in the destination directory -> flush -> fsync file -> atomic
rename -> fsync directory. A crash mid-write leaves only a dot-prefixed .tmp file
that consumers ignore; a partially written file never becomes visible under its
final name.
"""

from __future__ import annotations

import os
from pathlib import Path


def _fsync_dir(directory):
    """fsync a directory so a rename into it is durable (best-effort; some
    platforms disallow opening a dir — degrade quietly, never network)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path, text):
    """Durably, atomically write ``text`` to ``path`` (temp + fsync + rename)."""
    path = Path(path)
    tmp = path.parent / ("." + path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)   # atomic on the same filesystem
    _fsync_dir(path.parent)
    return path


def atomic_claim(src, dst):
    """Atomically move ``src`` -> ``dst`` via rename; the successful rename IS the
    claim. Returns True if this caller won the claim, False if it was already
    taken/absent (no lock files, no overwrite of a live claim)."""
    src, dst = Path(src), Path(dst)
    try:
        os.rename(src, dst)   # atomic; fails if src is gone (another claimer won)
    except (FileNotFoundError, OSError):
        return False
    _fsync_dir(dst.parent)
    return True


def atomic_move(src, dst):
    """Move a file to a terminal directory (archive/quarantine). Idempotent-safe:
    if src is already gone, returns False."""
    src, dst = Path(src), Path(dst)
    try:
        os.replace(src, dst)
    except (FileNotFoundError, OSError):
        return False
    _fsync_dir(dst.parent)
    return True


def append_line_fsync(path, line):
    """Append one line to a JSONL file durably (create if needed)."""
    path = Path(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return path
