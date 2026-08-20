"""Canonical single-owner OS process lock (the ONE process-lock primitive).

The single cross-process single-owner lock used by every Session Edge process that
must be the sole authority for a domain — the producer's entry-writer authority and
the manager's management authority. It is a sibling of ``atomic_claim``: both are
cross-process filesystem coordination primitives. A caller supplies a domain root
and a DISTINCT lock-file name, so independent authorities (producer vs manager)
never block one another, while two instances of the SAME authority do.

Mechanism: an OS-held EXCLUSIVE, NON-BLOCKING advisory lock on an open descriptor
(``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows). The kernel releases the
lock automatically when the descriptor is closed OR the owning process dies — so
ownership is proven by a LIVE held handle, never by a PID file or a timestamp. There
is no stale-owner takeover heuristic: a crash frees the lock at the OS level; a live
owner is never displaced. Safety over liveness — no split-brain is possible.

Fail closed: no lock primitive, an unreadable/invalid path/name, or any I/O error
during establishment yields NO ownership (the caller must refuse to run). The small
diagnostics payload (pid/host/started_at/domain/lock) written into the file is for
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


class ProcessLockError(RuntimeError):
    """Base for process-lock failures (always fail closed)."""


class ProcessLockHeld(ProcessLockError):
    """Another LIVE owner already holds this (domain, lock name)."""


class ProcessLockUnavailable(ProcessLockError):
    """The lock could not be established (no primitive / bad path / I/O error)."""


def canonical_domain(domain_root):
    """Canonical, spelling-independent identity of an ownership domain.

    ``resolve()`` yields an absolute real path (resolving ``..``, symlinks/junctions
    and trailing slashes); on Windows the filesystem is case-insensitive so distinct
    casings open the same inode. Two owners pointing at the same effective domain
    therefore map to the same lock file."""
    return Path(domain_root).expanduser().resolve()


class ProcessLock:
    """OS-held exclusive single-owner lock, keyed to (domain root, lock name).

    Acquire ONCE at process startup and hold for the whole authoritative lifetime
    (never per-cycle — that would reopen the between-cycles race). Release on
    graceful shutdown; a crash releases it automatically at the OS level."""

    def __init__(self, domain_root, *, lock_name):
        if not lock_name or "/" in lock_name or "\\" in lock_name:
            raise ProcessLockUnavailable(f"invalid lock name: {lock_name!r}")
        self.domain = canonical_domain(domain_root)
        self.lock_name = lock_name
        self.path = self.domain / lock_name
        self._fd = None
        self._locked = False

    # -- acquisition --------------------------------------------------------
    def acquire(self):
        """Take exclusive ownership or fail closed. Raises :class:`ProcessLockHeld`
        if a live owner already holds the (domain, lock name), or
        :class:`ProcessLockUnavailable` if the lock cannot be established."""
        if not (_HAVE_FCNTL or _HAVE_MSVCRT):        # pragma: no cover - exotic platform
            raise ProcessLockUnavailable("no OS file-lock primitive on this platform")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as exc:
            raise ProcessLockUnavailable(
                "cannot open lock {}: {}".format(self.path, exc)) from exc
        try:
            self._os_lock(fd)                        # raises ProcessLockHeld if contended
        except ProcessLockHeld:
            _safe_close(fd)
            raise
        except OSError as exc:                       # pragma: no cover - rare lock I/O error
            _safe_close(fd)
            raise ProcessLockUnavailable(
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
                raise ProcessLockHeld(
                    "another owner holds {}".format(self.path)) from exc
        else:                                        # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:                    # region locked -> held (fail closed)
                raise ProcessLockHeld(
                    "another owner holds {}".format(self.path)) from exc

    def _write_diagnostics(self):
        """Best-effort operator diagnostics. NOT authority — the OS lock is."""
        payload = "pid={} host={} started_at={} domain={} lock={}\n".format(
            os.getpid(), platform.node() or "unknown", int(time.time()),
            self.domain, self.lock_name)
        try:
            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, payload.encode("utf-8", "replace"))
            os.fsync(self._fd)
        except OSError:
            pass                                     # diagnostics only; lock still holds

    # -- release ------------------------------------------------------------
    def release(self):
        """Release ownership: unlock and close the handle (which also frees the OS
        lock). The file is intentionally NOT deleted — the OS lock, not file
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
        """The persisted pid/host/started_at/domain/lock line, or None. Diagnostics
        only; contains no credentials."""
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
