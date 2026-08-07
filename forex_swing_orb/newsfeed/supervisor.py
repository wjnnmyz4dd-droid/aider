"""Single-instance lock for the acquisition service (Phase 9D-R1-R, F-4).

Prevents duplicate acquisition processes writing the same news file. Restart-after-
crash and bounded restarts are delegated to the OS supervisor (Windows Task
Scheduler / systemd — see README), which is the simplest appropriate mechanism; this
module only guarantees "at most one instance" via an exclusive lock file.

Filesystem-only, no networking. Best-effort stale-lock reclaim on POSIX (a lock held
by a dead pid is reclaimed); on platforms where liveness can't be probed the lock is
conservatively honored (fail closed against duplicates).
"""

from __future__ import annotations

import os
from pathlib import Path


class LockHeld(RuntimeError):
    """Another live instance already holds the lock."""


def _pid_alive(pid):
    try:
        os.kill(pid, 0)               # POSIX liveness probe (no signal sent)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True                   # exists (or can't tell) -> treat as alive
    return True


class SingleInstanceLock:
    """Exclusive lock via ``O_CREAT | O_EXCL``. Use as a context manager."""

    def __init__(self, path):
        self.path = Path(path)
        self._fd = None

    def acquire(self):
        try:
            self._open_exclusive()
        except FileExistsError:
            if self._reclaim_if_stale():
                self._open_exclusive()
            else:
                raise LockHeld(f"acquisition lock held: {self.path}")
        return self

    def _open_exclusive(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.fsync(fd)
        self._fd = fd

    def _reclaim_if_stale(self):
        try:
            pid = int(self.path.read_text(encoding="ascii").strip() or "-1")
        except (OSError, ValueError):
            return False
        if pid > 0 and _pid_alive(pid):
            return False
        try:
            os.unlink(self.path)      # holder is dead -> reclaim
            return True
        except OSError:
            return False

    def release(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        try:
            self.path.unlink()
        except OSError:
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
