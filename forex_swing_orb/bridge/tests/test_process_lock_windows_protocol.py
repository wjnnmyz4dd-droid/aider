"""ProcessLock Windows lock-protocol hardening (real-Windows ownership repair).

Windows byte-range locks (msvcrt.locking -> LockFile) require every acquirer to lock
the EXACT same, EXISTING byte range, and forbid the diagnostics write from ever
leaving the lock file momentarily empty (which produced ``holder=None``). These are
deterministic, comment-aware proofs over the shipped primitive plus real
multiprocessing ownership. The POSIX path (flock) is size/region independent, so it
is used here as the CI oracle; the byte-range invariants are what protect Windows.
Actual msvcrt behavior is MANUAL WINDOWS VALIDATION (runbook).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.bridge.process_lock import (ProcessLock, ProcessLockHeld,  # noqa: E402
                                                 LOCK_BYTE_OFFSET, LOCK_BYTE_COUNT)

LOCK = ".pl.lock"


# --- fixed, existing lock region (Windows correctness precondition) ----------
def test_lock_region_is_fixed_single_byte_at_zero():
    assert LOCK_BYTE_OFFSET == 0 and LOCK_BYTE_COUNT == 1


def test_lock_file_is_non_empty_after_acquire(tmp_path):
    lk = ProcessLock(tmp_path, lock_name=LOCK).acquire()
    try:
        # the guarded byte (offset 0) must EXIST -> file has >= 1 byte
        assert lk.path.stat().st_size >= 1
        # diagnostics are populated (no holder=None for our own live lock)
        assert (lk.owner_diagnostics() or "").startswith("pid=")
    finally:
        lk.release()


def test_diagnostics_write_never_empties_the_file(tmp_path):
    # re-acquiring rewrites diagnostics; at no observable point is the file empty
    # (write-then-truncate-to-len, never truncate-to-0). Proven by content always
    # present and starting with pid= across repeated cycles.
    p = None
    for _ in range(6):
        lk = ProcessLock(tmp_path, lock_name=LOCK).acquire()
        p = lk.path
        assert p.stat().st_size >= 1
        assert (lk.owner_diagnostics() or "").startswith("pid=")
        lk.release()
        assert p.stat().st_size >= 1                  # file persists between owners


def test_empty_leftover_file_does_not_block(tmp_path):
    # a zero-length leftover lock file (e.g. sentinel-only from a crash before
    # diagnostics) must not block acquisition, and must end up non-empty.
    lf = tmp_path / LOCK
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.write_bytes(b"")                               # zero length
    lk = ProcessLock(tmp_path, lock_name=LOCK).acquire()
    try:
        assert lk.held and lf.stat().st_size >= 1
    finally:
        lk.release()


def test_corrupt_nonempty_leftover_does_not_block_and_is_rewritten(tmp_path):
    lf = tmp_path / LOCK
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.write_text("pid=999999 host=ghost garbage!! not-valid", encoding="utf-8")
    lk = ProcessLock(tmp_path, lock_name=LOCK).acquire()
    try:
        assert lk.held
        assert (lk.owner_diagnostics() or "").startswith("pid=")   # rewritten cleanly
    finally:
        lk.release()


def test_no_false_held_when_no_live_owner(tmp_path):
    # leftover artifact + NO live owner -> acquires (never a false HELD_BY_OTHER)
    lf = tmp_path / LOCK
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.write_text("pid=4242 host=old", encoding="utf-8")
    lk = ProcessLock(tmp_path, lock_name=LOCK).acquire()
    try:
        assert lk.held
    finally:
        lk.release()


def test_live_owner_never_displaced_and_file_not_deleted(tmp_path):
    a = ProcessLock(tmp_path, lock_name=LOCK).acquire()
    try:
        with pytest.raises(ProcessLockHeld):
            ProcessLock(tmp_path, lock_name=LOCK).acquire()
        assert a.path.exists()                        # never deleted while live-held
        assert a.held
    finally:
        a.release()


def test_release_then_immediate_reacquire(tmp_path):
    a = ProcessLock(tmp_path, lock_name=LOCK).acquire()
    a.release()
    b = ProcessLock(tmp_path, lock_name=LOCK).acquire()   # no manual cleanup needed
    try:
        assert b.held
    finally:
        b.release()


# --- multiprocessing: OS auto-release on death (the real production model) ----
def _mp_hold(domain, name, ready, release, q):
    from forex_swing_orb.bridge.process_lock import ProcessLock as _PL
    from forex_swing_orb.bridge.process_lock import ProcessLockHeld as _Held
    try:
        lk = _PL(domain, lock_name=name).acquire()
    except _Held:
        q.put("refused"); return
    q.put("acquired"); ready.set(); release.wait(10); lk.release()


def _mp_hold_then_die(domain, name, ready):
    from forex_swing_orb.bridge.process_lock import ProcessLock as _PL
    _PL(domain, lock_name=name).acquire()
    ready.set()
    os._exit(0)                                       # die WITHOUT release -> OS frees it


def _ctx():
    import multiprocessing as mp
    return mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()


def test_multiprocess_single_owner(tmp_path):
    ctx = _ctx(); dom = str(tmp_path / "d")
    ready = ctx.Event(); release = ctx.Event(); q = ctx.Queue()
    a = ctx.Process(target=_mp_hold, args=(dom, LOCK, ready, release, q)); a.start()
    assert ready.wait(10) and q.get(timeout=10) == "acquired"
    ready_b = ctx.Event(); q_b = ctx.Queue()
    b = ctx.Process(target=_mp_hold, args=(dom, LOCK, ready_b, release, q_b)); b.start(); b.join(10)
    assert q_b.get(timeout=10) == "refused"
    release.set(); a.join(10)


def test_multiprocess_death_auto_releases(tmp_path):
    ctx = _ctx(); dom = str(tmp_path / "d")
    ready = ctx.Event()
    dead = ctx.Process(target=_mp_hold_then_die, args=(dom, LOCK, ready)); dead.start()
    assert ready.wait(10); dead.join(10)
    assert dead.exitcode == 0
    lk = ProcessLock(dom, lock_name=LOCK).acquire()   # kernel freed the dead lock
    try:
        assert lk.held
    finally:
        lk.release()
