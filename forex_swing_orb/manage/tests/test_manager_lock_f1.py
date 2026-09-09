"""F1 manager single-instance ownership lock (cross-repo audit finding).

At most ONE manager process may own management authority for a Session Edge
management domain at a time. A second manager must FAIL CLOSED before it evaluates
positions, runs orphan recovery, reconciles, emits a manage instruction, or writes
its health artifact. The producer already enforces this for the entry channel via
producer/writer_lock.py; F1 gives the manager the SAME guarantee by reusing the
ONE canonical OS process-lock primitive (bridge.process_lock.ProcessLock) with a
DISTINCT lock identity — so a producer and a manager never block one another while
two managers do.

Deterministic; POSIX flock / Windows msvcrt via the shared primitive; a real
multiprocessing ownership test (threads alone cannot prove the production model).
Windows behavior is MANUAL DEMO VALIDATION.
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
                                                ProcessLockUnavailable, canonical_domain)
from forex_swing_orb.manage.manager_lock import (ManagerLock, ManagerLockHeld,  # noqa: E402
                                                _LOCK_NAME as MANAGER_LOCK_NAME)
from forex_swing_orb.producer.writer_lock import ProducerWriterLock  # noqa: E402


# ============================================================================
# CANONICAL PRIMITIVE — ONE implementation, separate identities
# ============================================================================
def test_1_first_manager_acquires(tmp_path):
    lk = ManagerLock(tmp_path).acquire()
    try:
        assert lk.held
        assert lk.path.name == MANAGER_LOCK_NAME
    finally:
        lk.release()
    assert not lk.held


def test_2_13_second_manager_same_domain_refused(tmp_path):
    a = ManagerLock(tmp_path).acquire()
    b = ManagerLock(tmp_path)
    try:
        with pytest.raises(ManagerLockHeld):
            b.acquire()
    finally:
        a.release()


def test_10_release_then_reacquire(tmp_path):
    a = ManagerLock(tmp_path).acquire()
    a.release()
    b = ManagerLock(tmp_path).acquire()          # domain free again
    try:
        assert b.held
    finally:
        b.release()


def test_11_producer_and_manager_locks_coexist(tmp_path):
    # DISTINCT identities on the SAME domain must NOT block one another.
    p = ProducerWriterLock(tmp_path).acquire()
    m = ManagerLock(tmp_path).acquire()
    try:
        assert p.held and m.held
        assert p.path.name != m.path.name
    finally:
        p.release()
        m.release()


def test_14_different_domains_do_not_conflict(tmp_path):
    a = ManagerLock(tmp_path / "acct_X" / "bridge").acquire()
    b = ManagerLock(tmp_path / "acct_Y" / "bridge").acquire()
    try:
        assert a.held and b.held
    finally:
        a.release()
        b.release()


def test_15_lock_identity_deterministic(tmp_path):
    assert canonical_domain(tmp_path) == canonical_domain(str(tmp_path) + "/./")
    assert ManagerLock(tmp_path).path == ManagerLock(str(tmp_path) + "/./").path


def test_one_canonical_primitive_no_duplicate_algorithm():
    # ManagerLock and ProducerWriterLock must both be the SAME primitive, not two
    # copied locking algorithms.
    assert issubclass(ManagerLock, ProcessLock)
    assert issubclass(ProducerWriterLock, ProcessLock)
    # exceptions unified (manager held-error IS the canonical held-error)
    assert ManagerLockHeld is ProcessLockHeld


def test_same_domain_spelling_conflicts(tmp_path):
    root = tmp_path / "bridge"; root.mkdir()
    a = ManagerLock(str(root)).acquire()
    try:
        for spelling in (str(root) + "/", str(root) + "/./", os.path.relpath(str(root))):
            with pytest.raises(ManagerLockHeld):
                ManagerLock(spelling).acquire()
    finally:
        a.release()


# ============================================================================
# ENTRYPOINT — second manager fails closed BEFORE any management work
# ============================================================================
class _FakeTruth:
    def terminal_connected(self):
        return True


class _FakeService:
    """Minimal stand-in for ManagerService for entrypoint wiring tests."""
    def __init__(self, root):
        from forex_swing_orb.manage.paths import ManagePaths
        self.paths = ManagePaths(root).ensure()
        self._truth = _FakeTruth()
        self._cadence_sec = 900
        self._last_error = None
        self.run_once_calls = 0
        self.health_path = str(self.paths.root / "manager_health.json")

    def run_once(self, now):
        self.run_once_calls += 1

    def reconcile_outcomes(self, now):
        return []


def _patch_build(monkeypatch, service):
    from forex_swing_orb.manage import __main__ as M
    monkeypatch.setattr(M.ManagerService, "build_from_env", classmethod(lambda cls: service))
    monkeypatch.setattr(M, "_preflight", lambda s: None)
    return M


def test_3_4_5_6_second_manager_refused_does_no_work(tmp_path, monkeypatch):
    from forex_swing_orb.manage import __main__ as M
    svc = _FakeService(tmp_path)
    _patch_build(monkeypatch, svc)
    # manager A already owns the domain
    a = ManagerLock(svc.paths.root).acquire()
    try:
        rc = M.main([])
    finally:
        a.release()
    assert rc == 4                                   # fail closed, distinct refusal code
    assert svc.run_once_calls == 0                   # no evaluation / recovery / emission
    assert not Path(svc.health_path).exists()        # did not clobber active manager health


def test_16_launcher_double_start_single_owner(tmp_path, monkeypatch):
    # simulate the launcher starting a manager while one already owns the domain:
    # the second manager main() refuses (same mechanism as a manual double-launch).
    from forex_swing_orb.manage import __main__ as M
    svc = _FakeService(tmp_path)
    _patch_build(monkeypatch, svc)
    owner = ManagerLock(svc.paths.root).acquire()
    try:
        assert M.main([]) == 4
    finally:
        owner.release()


def test_7_8_lock_released_after_normal_exit(tmp_path, monkeypatch):
    from forex_swing_orb.manage import __main__ as M
    svc = _FakeService(tmp_path)
    _patch_build(monkeypatch, svc)

    class _StubLoop:
        def __init__(self, service):
            self.service = service
        def run(self, max_cycles=None):
            return None                              # exit immediately (normal shutdown)
    monkeypatch.setattr(M, "_Loop", _StubLoop)

    rc = M.main([])
    assert rc == 0
    # the lock must have been released on normal exit -> a new owner can acquire
    after = ManagerLock(svc.paths.root).acquire()
    try:
        assert after.held
    finally:
        after.release()


def test_8b_lock_released_after_loop_exception(tmp_path, monkeypatch):
    from forex_swing_orb.manage import __main__ as M
    svc = _FakeService(tmp_path)
    _patch_build(monkeypatch, svc)

    class _BoomLoop:
        def __init__(self, service):
            self.service = service
        def run(self, max_cycles=None):
            raise RuntimeError("loop blew up")
    monkeypatch.setattr(M, "_Loop", _BoomLoop)

    with pytest.raises(RuntimeError):
        M.main([])
    # even on an unhandled loop exception the lock is released (finally)
    after = ManagerLock(svc.paths.root).acquire()
    try:
        assert after.held
    finally:
        after.release()


def test_happy_path_acquires_and_runs(tmp_path, monkeypatch):
    from forex_swing_orb.manage import __main__ as M
    svc = _FakeService(tmp_path)
    _patch_build(monkeypatch, svc)
    ran = {"n": 0}

    class _OneCycleLoop:
        def __init__(self, service):
            self.service = service
        def run(self, max_cycles=None):
            ran["n"] += 1
    monkeypatch.setattr(M, "_Loop", _OneCycleLoop)

    assert M.main([]) == 0
    assert ran["n"] == 1                             # the sole owner ran the loop


# ============================================================================
# MULTIPROCESS — real cross-process ownership (production model)
# ============================================================================
def _mp_try_acquire(domain_str, ready_evt, release_evt, result_q):
    from forex_swing_orb.manage.manager_lock import ManagerLock as _ML
    from forex_swing_orb.manage.manager_lock import ManagerLockHeld as _Held
    lk = _ML(domain_str)
    try:
        lk.acquire()
    except _Held:
        result_q.put("refused")
        return
    result_q.put("acquired")
    ready_evt.set()
    release_evt.wait(10)
    lk.release()


def test_multiprocess_single_owner(tmp_path):
    import multiprocessing as mp
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    domain = str(tmp_path / "bridge")
    ready = ctx.Event(); release = ctx.Event(); q = ctx.Queue()
    # process A acquires and holds
    a = ctx.Process(target=_mp_try_acquire, args=(domain, ready, release, q))
    a.start()
    assert ready.wait(10), "process A did not acquire"
    assert q.get(timeout=10) == "acquired"
    # process B tries the same domain while A holds -> must be refused
    ready_b = ctx.Event(); q_b = ctx.Queue()
    b = ctx.Process(target=_mp_try_acquire, args=(domain, ready_b, release, q_b))
    b.start()
    b.join(10)
    assert q_b.get(timeout=10) == "refused"          # exactly one owner
    # release A -> a fresh acquire now succeeds (ownership transfer after exit)
    release.set()
    a.join(10)
    c = ManagerLock(domain).acquire()
    try:
        assert c.held
    finally:
        c.release()
