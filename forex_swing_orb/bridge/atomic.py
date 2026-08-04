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
    """Exclusively claim ``src`` -> ``dst`` (F-A). Uses hardlink + unlink so the
    claim FAILS (never overwrites) if ``dst`` already exists, consistently across
    platforms. Returns True iff this caller won the claim; False if the
    destination already exists or the source is gone (no lock files)."""
    src, dst = Path(src), Path(dst)
    try:
        os.link(src, dst)     # atomic; raises FileExistsError if dst exists
    except FileExistsError:
        return False          # destination already claimed — never overwrite
    except (FileNotFoundError, OSError):
        return False          # source gone (another claimer won) or unsupported
    try:
        os.unlink(src)        # drop the pending link; dst now owns the inode
    except OSError:
        pass                  # dst is claimed regardless; a stray src is harmless
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
    """Append one line to a JSONL file durably (create if needed). On first
    creation the containing directory is fsync'd too (F-1)."""
    path = Path(path)
    created = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    if created:
        _fsync_dir(path.parent)
    return path
