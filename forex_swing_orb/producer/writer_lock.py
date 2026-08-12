"""Producer single-writer authority lock (F-3).

Only ONE producer may hold entry-authorization writer authority for a given entry
bridge at a time. A second producer targeting the same bridge MUST fail closed
BEFORE it evaluates a market, authorizes a candidate, or writes an instruction.

Authority domain: the ENTRY BRIDGE ROOT (canonicalized). All producers that write
entry instructions to the same effective bridge share one lock; producers on
genuinely separate bridge roots are independent. Same bridge reached by different
textual paths (relative/absolute, symlink, trailing slash, Windows case) resolves
to the SAME file inode, so the OS lock is on the same object regardless of spelling.

Mechanism: an OS-held EXCLUSIVE, NON-BLOCKING advisory lock on an open descriptor
(``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows). The kernel releases the
lock automatically when the descriptor is closed OR the owning process dies — so
authority is proven by a LIVE held handle, never by a PID file or a timestamp. There
is no stale-owner takeover heuristic: a crash frees the lock at the OS level; a live
owner is never displaced. Safety over liveness — no split-brain is possible.

Fail closed: no lock primitive, an unreadable/invalid path, or any I/O error during
establishment yields NO writer authority (the producer refuses to start). The small
diagnostics payload (pid/host/started_at/domain) written into the file is for
operators only — the OS lock, not the file's contents, is the authority.
"""

from __future__ import annotations

import os
import platform
import time
from pathlib import Path

try:                                   # POSIX
    import fcntl
    _HAVE_FCNTL = True
except ImportError:                    # pragma: no cover - non-POSIX
    _HAVE_FCNTL = False

try:                                   # Windows
    import msvcrt
    _HAVE_MSVCRT = True
except ImportError:                    # pragma: no cover - non-Windows
    _HAVE_MSVCRT = False

_LOCK_NAME = ".producer_writer.lock"   # dot-file at the bridge root; never an instruction


class ProducerLockError(RuntimeError):
    """Base for producer writer-lock failures (always fail closed)."""


class ProducerLockHeld(ProducerLockError):
    """Another LIVE producer already holds writer authority for this bridge domain."""


class ProducerLockUnavailable(ProducerLockError):
    """The lock could not be established (no primitive / bad path / I/O error)."""


def canonical_domain(bridge_root):
    """Canonical, spelling-independent identity of the entry-bridge writer domain.

    ``resolve()`` yields an absolute real path (resolving ``..``, symlinks/junctions
    and trailing slashes); on Windows the filesystem is case-insensitive so distinct
    casings open the same inode. Two producers pointing at the same effective bridge
    therefore map to the same lock file."""
    return Path(bridge_root).expanduser().resolve()


class ProducerWriterLock:
    """OS-held exclusive single-writer lock, keyed to the entry-bridge root.

    Acquire ONCE at producer startup and hold for the whole authoritative lifetime
    (never per-cycle — that would reopen the between-cycles race). Release on
    graceful shutdown; a crash releases it automatically at the OS level."""

    def __init__(self, bridge_root):
        self.domain = canonical_domain(bridge_root)
        self.path = self.domain / _LOCK_NAME
        self._fd = None
        self._locked = False

    # -- acquisition --------------------------------------------------------
    def acquire(self):
        """Take exclusive writer authority or fail closed. Raises
        :class:`ProducerLockHeld` if a live producer already owns the domain, or
        :class:`ProducerLockUnavailable` if the lock cannot be established."""
        if not (_HAVE_FCNTL or _HAVE_MSVCRT):        # pragma: no cover - exotic platform
            raise ProducerLockUnavailable("no OS file-lock primitive on this platform")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as exc:
            raise ProducerLockUnavailable(
                "cannot open producer lock {}: {}".format(self.path, exc)) from exc
        try:
            self._os_lock(fd)                        # raises ProducerLockHeld if contended
        except ProducerLockHeld:
            _safe_close(fd)
            raise
        except OSError as exc:                       # pragma: no cover - rare lock I/O error
            _safe_close(fd)
            raise ProducerLockUnavailable(
                "cannot lock {}: {}".format(self.path, exc)) from exc
        self._fd = fd
        self._locked = True
        self._write_diagnostics()
        return self

    def _os_lock(self, fd):
        if _HAVE_FCNTL:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:           # already held by a live process
                raise ProducerLockHeld(
                    "another producer holds writer authority for {}".format(self.domain)) from exc
        else:                                        # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:                   # region locked -> held (fail closed)
                raise ProducerLockHeld(
                    "another producer holds writer authority for {}".format(self.domain)) from exc

    def _write_diagnostics(self):
        """Best-effort operator diagnostics. NOT authority — the OS lock is."""
        payload = "pid={} host={} started_at={} domain={}\n".format(
            os.getpid(), platform.node() or "unknown", int(time.time()), self.domain)
        try:
            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, payload.encode("utf-8", "replace"))
            os.fsync(self._fd)
        except OSError:
            pass                                     # diagnostics only; lock still holds

    # -- release ------------------------------------------------------------
    def release(self):
        """Release writer authority: unlock and close the handle (which also frees
        the OS lock). The file is intentionally NOT deleted — the OS lock, not file
        existence, is authority, and unlinking a file another process may re-lock is
        unsafe across platforms."""
        fd, self._fd, self._locked = self._fd, None, False
        if fd is None:
            return
        try:
            if _HAVE_FCNTL:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:                                    # pragma: no cover - Windows only
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            _safe_close(fd)

    # -- observability (no secrets) ----------------------------------------
    @property
    def held(self):
        return self._locked

    def owner_diagnostics(self):
        """The persisted pid/host/started_at/domain line, or None. Diagnostics only;
        contains no credentials."""
        try:
            return self.path.read_text(encoding="utf-8", errors="replace").strip() or None
        except OSError:
            return None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def _safe_close(fd):
    try:
        os.close(fd)
    except OSError:                                  # pragma: no cover
        pass
