"""News-acquisition single-owner authority lock (self-healing hardening).

At most ONE live news-acquisition process may own acquisition authority for a
Session Edge news domain at a time. A second live acquirer MUST fail closed BEFORE
it fetches, validates, or writes the news bundle the compliance layer reads.

This is a thin ACQUISITION IDENTITY over the ONE canonical process-lock primitive
:class:`forex_swing_orb.bridge.process_lock.ProcessLock` -- the SAME primitive the
producer (``producer/writer_lock.py``) and manager (``manage/manager_lock.py``) use,
with a DISTINCT lock name so acquisition, producer, and manager on the same tree
never block one another while two acquirers do. It reimplements NO locking
algorithm and adds NO trade/compliance authority: ``compliance/news.py`` remains the
sole news authority and this process still only writes the data file.

WHY THIS REPLACES THE OLD PID-FILE LOCK
---------------------------------------
The previous ``supervisor.SingleInstanceLock`` proved ownership with an
``O_CREAT|O_EXCL`` PID file plus a ``os.kill(pid, 0)`` liveness probe for stale
reclaim. On Windows that probe is wrong in BOTH directions:

  * a DEAD pid makes ``OpenProcess`` fail, so Python raises ``OSError`` (winerror
    87) -- NOT ``ProcessLookupError`` (the POSIX-only mapping the old code assumed).
    The old ``_pid_alive`` caught ``OSError`` and returned "alive", so a dead
    owner's PID file could NEVER be reclaimed -> "another acquisition instance is
    running; refusing to start" forever, with no python.exe running (the exact
    reported Windows defect); and
  * a LIVE pid makes ``os.kill(pid, 0)`` call ``TerminateProcess(handle, 0)`` on
    Windows -- it would KILL whatever process currently holds that (possibly reused)
    pid.

The canonical OS lock removes both hazards: the kernel releases the lock
automatically when the owning process dies, so a dead owner NEVER blocks startup
(self-healing), a live owner is NEVER displaced, and no process is ever terminated.
Ownership is proven by a LIVE held handle, never by a PID file or a timestamp; file
age is never used as proof of death.

OWNERSHIP STATES (observational; the OS lock is the authority)
  ACQUIRED         -- ownership taken; no prior artifact was present (fresh start).
  STALE_RECOVERED  -- ownership taken; a leftover ownership artifact was present but
                      NO live owner held it, so it was safely superseded (expected
                      after a crash, forced kill, reboot, or ordinary restart).
  HELD_BY_OTHER    -- a live owner holds the domain; refuse, mutate nothing.
  UNKNOWN          -- ownership could not be established (no primitive / bad path /
                      I/O error); fail closed.
  ERROR            -- unexpected failure; fail closed.
"""

from __future__ import annotations

from pathlib import Path

from ..bridge.process_lock import (ProcessLock, ProcessLockError, ProcessLockHeld,
                                    ProcessLockUnavailable, canonical_domain)

# Acquisition-facing names (the canonical exceptions, aliased for readable call sites
# and backward compatibility with the old supervisor import surface).
NewsAcquisitionLockError = ProcessLockError
NewsAcquisitionLockHeld = ProcessLockHeld
NewsAcquisitionLockUnavailable = ProcessLockUnavailable

__all__ = ["NewsAcquisitionLock", "NewsAcquisitionLockError", "NewsAcquisitionLockHeld",
           "NewsAcquisitionLockUnavailable", "AcquisitionOwnerState",
           "acquire_ownership", "probe_ownership", "canonical_domain"]


class AcquisitionOwnerState:
    """Explicit, truthful news-acquisition ownership states (see module docstring)."""
    ACQUIRED = "ACQUIRED"
    STALE_RECOVERED = "STALE_RECOVERED"
    HELD_BY_OTHER = "HELD_BY_OTHER"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"

    #: states in which THIS process owns acquisition authority and may run.
    OWNING = frozenset({ACQUIRED, STALE_RECOVERED})
    #: states in which THIS process must refuse to run (fail closed).
    REFUSING = frozenset({HELD_BY_OTHER, UNKNOWN, ERROR})


class NewsAcquisitionLock(ProcessLock):
    """OS-held exclusive single-owner lock for the news-acquisition domain.

    Constructed from the configured LOCK-FILE PATH (kept identical to the previous
    ``SingleInstanceLock`` surface) so operator configuration is unchanged; the
    file's directory is the ownership domain and its name the lock name. Acquire
    ONCE at startup and hold for the whole lifetime; release on graceful shutdown (a
    crash releases it automatically at the OS level). Thin identity over the
    canonical :class:`ProcessLock` -- no locking algorithm is reimplemented here."""

    def __init__(self, lock_path):
        p = Path(lock_path)
        name = p.name
        if not name:
            raise ProcessLockUnavailable(f"invalid acquisition lock path: {lock_path!r}")
        parent = p.parent if str(p.parent) not in ("", ".") else Path(".")
        super().__init__(parent, lock_name=name)


def acquire_ownership(lock_path, *, logger=None):
    """Attempt single-owner news-acquisition ownership. Self-healing and fail-closed.

    Returns ``(lock_or_None, state, detail)`` where ``state`` is an
    :class:`AcquisitionOwnerState` value. NEVER deletes a lock file and NEVER
    terminates any process: recovery is by the kernel having already freed a dead
    owner's lock, proven by our successfully taking the OS lock. A live owner is
    detected via lock contention and is never displaced; an unknown/ambiguous
    outcome fails closed.

    * no lock_path configured        -> (None, UNKNOWN, ...)
    * live owner holds the domain    -> (None, HELD_BY_OTHER, {holder diagnostics})
    * lock cannot be established      -> (None, UNKNOWN, {reason})
    * unexpected failure             -> (None, ERROR, {reason})
    * acquired, no prior artifact     -> (lock, ACQUIRED, {})
    * acquired, prior artifact present -> (lock, STALE_RECOVERED, {prior_owner})
    """
    if not lock_path:
        return (None, AcquisitionOwnerState.UNKNOWN,
                {"reason": "no acquisition lock path configured"})
    try:
        lock = NewsAcquisitionLock(lock_path)
    except ProcessLockError as exc:                  # bad path / no primitive
        return (None, AcquisitionOwnerState.UNKNOWN, {"reason": repr(exc)})

    # Read any leftover ownership artifact BEFORE acquiring (read-only; never deleted).
    # Its mere presence is NOT proof of a live owner -- the OS lock decides that.
    pre_existed = lock.path.exists()
    prior_owner = lock.owner_diagnostics() if pre_existed else None

    try:
        lock.acquire()
    except ProcessLockHeld:                           # a LIVE owner holds the OS lock
        # The OS lock -- not this metadata -- proved a live owner exists. Holder
        # identity is best-effort: it can be None if the live owner is between taking
        # the lock and writing its diagnostics, or if the file is transiently
        # unreadable. A None holder NEVER downgrades the HELD_BY_OTHER decision.
        holder = lock.owner_diagnostics()
        detail = {"holder": holder, "lock_path": str(lock.path), "contended": True}
        if not holder:
            detail["holder_note"] = ("a live owner holds the OS lock but has not yet "
                                     "published (or we could not read) its identity")
        return (None, AcquisitionOwnerState.HELD_BY_OTHER, detail)
    except ProcessLockUnavailable as exc:             # no primitive / I/O error at open/lock
        return (None, AcquisitionOwnerState.UNKNOWN,
                {"reason": repr(exc), "lock_path": str(lock.path), "contended": False})
    except Exception as exc:                          # defensive: fail closed on anything
        return (None, AcquisitionOwnerState.ERROR,
                {"reason": repr(exc), "lock_path": str(lock.path)})

    if pre_existed:
        detail = {"prior_owner": prior_owner, "lock_path": str(lock.path)}
        if logger is not None:
            logger.warning(
                "STALE_ACQUISITION_OWNER_RECOVERED: superseded a leftover news-"
                "acquisition ownership artifact with no live owner (expected after a "
                "crash, forced termination, reboot, or restart). previous_owner=%s",
                prior_owner)
        return (lock, AcquisitionOwnerState.STALE_RECOVERED, detail)
    return (lock, AcquisitionOwnerState.ACQUIRED, {"lock_path": str(lock.path)})


def probe_ownership(lock_path):
    """READ-ONLY, NON-DESTRUCTIVE ownership probe for diagnostics/recovery.

    Attempts to take the OS lock and, on success, IMMEDIATELY releases it -- so this
    only observes whether a LIVE owner currently exists; it never keeps ownership,
    never deletes a lock file, and never kills a process. Returns ``(state, detail)``:

      * ACQUIRED / STALE_RECOVERED -> no live owner right now (safe to start; a leftover
        artifact, if any, is harmless and will self-heal).
      * HELD_BY_OTHER              -> a live Session Edge news process holds the lock.
      * UNKNOWN / ERROR            -> ownership could not be determined (fail closed).

    NB: this is a point-in-time observation; between probing and starting, ownership
    can change. The authoritative single-owner guarantee is still the live acquire in
    the service, never this probe.
    """
    lock, state, detail = acquire_ownership(lock_path)
    if lock is not None:
        lock.release()                                # observe only; never keep ownership
    return (state, detail)
