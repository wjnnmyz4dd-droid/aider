"""News-acquisition single-instance / stale-lock SELF-HEALING hardening.

Proves the invariant after crashes, forced termination, reboot, stale ownership
artifacts, or interrupted startup:

    AT MOST ONE LIVE NEWS ACQUISITION OWNER MAY EXIST FOR A DOMAIN.
    A dead owner must NEVER permanently block startup.
    A live owner must NEVER be displaced by stale-lock recovery.
    UNKNOWN must fail closed. Recovery must never kill a process or authorize a trade.

Root cause fixed: the old PID-file lock used ``os.kill(pid, 0)`` for stale reclaim.
On Windows a DEAD pid raises ``OSError`` (winerror 87), NOT ``ProcessLookupError``,
so the old ``_pid_alive`` treated the dead owner as alive and refused startup
forever; a LIVE pid would have been TerminateProcess'd. The fix reuses the ONE
canonical OS process-lock primitive (``bridge.process_lock.ProcessLock``): the
kernel frees a dead owner's lock automatically, so no PID liveness probe -- and no
``os.kill`` -- is used at all.

Deterministic; POSIX flock / Windows msvcrt via the shared primitive. Real
multiprocessing where the production model requires it. Windows behavior is MANUAL
DEMO VALIDATION (labeled in the runbook).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.bridge.process_lock import (ProcessLock, ProcessLockHeld,  # noqa: E402
                                                 ProcessLockUnavailable)
from forex_swing_orb.newsfeed import acquisition_lock as AL  # noqa: E402
from forex_swing_orb.newsfeed.acquisition_lock import (AcquisitionOwnerState as S,  # noqa: E402
                                                       NewsAcquisitionLock,
                                                       NewsAcquisitionLockHeld,
                                                       acquire_ownership)
from forex_swing_orb.manage.manager_lock import ManagerLock  # noqa: E402
from forex_swing_orb.producer.writer_lock import ProducerWriterLock  # noqa: E402

NOW = datetime(2024, 1, 10, 12, 0, tzinfo=timezone.utc)


# ============================================================================
# SINGLE AUTHORITY — one canonical primitive, no duplicate locking algorithm
# ============================================================================
def test_10_one_canonical_primitive_no_duplicate_algorithm():
    # The acquisition lock IS the canonical ProcessLock (subclass), not a second
    # copied algorithm; its held-error is the canonical held-error.
    assert issubclass(NewsAcquisitionLock, ProcessLock)
    assert NewsAcquisitionLockHeld is ProcessLockHeld
    # the historical supervisor surface delegates to the SAME class (no second lock)
    from forex_swing_orb.newsfeed import supervisor
    assert supervisor.SingleInstanceLock is NewsAcquisitionLock
    assert supervisor.LockHeld is ProcessLockHeld


def test_distinct_identity_coexists_with_producer_and_manager(tmp_path):
    # placed on the SAME domain, the three authorities must NOT block one another.
    a = NewsAcquisitionLock(str(tmp_path / ".news_acq.lock")).acquire()
    p = ProducerWriterLock(tmp_path).acquire()
    m = ManagerLock(tmp_path).acquire()
    try:
        assert a.held and p.held and m.held
        assert len({a.path.name, p.path.name, m.path.name}) == 3
    finally:
        a.release(); p.release(); m.release()


def test_16_recovery_module_has_no_trade_authority():
    # Acquisition ownership must never import or call into execution / orders /
    # positions / compliance / risk. Inspect real imports via AST (prose-immune).
    import ast
    tree = ast.parse(Path(AL.__file__).read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    forbidden = ("compliance", "producer", "manage", "ea_mt5", "position", "live",
                 "runtime", "research", "session")
    for m in modules:
        assert not any(f in m for f in forbidden), f"acquisition_lock imports {m!r}"
    # executable call tokens that must never appear — inspect the source with the
    # module docstring removed (prose lives only there).
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    code_nodoc = ast.unparse(ast.Module(body=body, type_ignores=[]))
    for banned in ("order_send", "OrderSend", "gate_news", "place_order",
                   "write_instruction", "authorize", "verified"):
        assert banned not in code_nodoc, f"acquisition_lock must not reference {banned!r}"


# ============================================================================
# STATE MACHINE — ACQUIRED / STALE_RECOVERED / HELD_BY_OTHER / UNKNOWN
# ============================================================================
def test_1_fresh_acquire_reports_acquired(tmp_path):
    lock, state, detail = acquire_ownership(str(tmp_path / "acq.lock"))
    try:
        assert state == S.ACQUIRED and lock.held
        assert detail.get("lock_path")               # diagnostic path surfaced
        assert "prior_owner" not in detail           # fresh: no leftover artifact
    finally:
        lock.release()


def test_3_8_stale_artifact_never_blocks_restart(tmp_path):
    lf = tmp_path / "acq.lock"
    # a leftover artifact from a prior (now-gone) owner, no live OS lock behind it
    lf.write_text("pid=999999 host=oldbox started_at=1 domain=x lock=acq.lock\n")
    # repeated restarts after "crash" all succeed and report STALE_RECOVERED
    for _ in range(5):
        lock, state, detail = acquire_ownership(str(lf))
        assert state == S.STALE_RECOVERED and lock.held
        assert detail.get("prior_owner")            # prior diagnostics captured for audit
        lock.release()                              # ProcessLock leaves the file in place


def test_4_live_owner_is_never_displaced(tmp_path):
    lf = tmp_path / "acq.lock"
    owner, s0, _ = acquire_ownership(str(lf))
    assert s0 == S.ACQUIRED
    try:
        # a second startup while the first LIVE owner holds it -> HELD_BY_OTHER
        second, state, detail = acquire_ownership(str(lf))
        assert second is None and state == S.HELD_BY_OTHER
        assert detail.get("holder") is not None     # live holder diagnostics surfaced
        assert lf.exists()                          # artifact NOT deleted/mutated
        assert owner.held                           # the live owner still owns it
    finally:
        owner.release()


def test_6_unknown_fails_closed_and_is_not_stale(tmp_path, monkeypatch):
    # no configured path -> UNKNOWN (never treated as ownable / stale)
    lock, state, _ = acquire_ownership(None)
    assert lock is None and state == S.UNKNOWN
    assert state in S.REFUSING and state not in S.OWNING
    # lock cannot be established (I/O error at establishment) -> UNKNOWN, fail closed

    def _boom(self):
        raise ProcessLockUnavailable("simulated I/O failure establishing lock")
    monkeypatch.setattr(NewsAcquisitionLock, "acquire", _boom, raising=True)
    lock2, state2, _ = acquire_ownership(str(tmp_path / "acq.lock"))
    assert lock2 is None and state2 == S.UNKNOWN


def test_7_recovery_is_idempotent(tmp_path):
    lf = tmp_path / "acq.lock"
    seen = []
    for i in range(4):
        lock, state, _ = acquire_ownership(str(lf))
        seen.append(state)
        lock.release()
    assert seen[0] == S.ACQUIRED
    assert all(s == S.STALE_RECOVERED for s in seen[1:])   # deterministic thereafter


# ============================================================================
# NO os.kill — the exact Windows defect can never recur
# ============================================================================
def test_5_9_no_process_kill_and_pid_reuse_cannot_prove_ownership(tmp_path, monkeypatch):
    # Guard: if recovery ever calls os.kill again, fail loudly.
    def _forbidden_kill(*a, **k):
        raise AssertionError("acquisition recovery must NEVER call os.kill")
    monkeypatch.setattr(os, "kill", _forbidden_kill)

    lf = tmp_path / "acq.lock"
    # leftover artifact naming a LIVE pid (our own) — PID reuse must NOT falsely
    # prove ownership: no OS lock is held behind the file, so we self-heal anyway.
    lf.write_text(f"pid={os.getpid()} host=me started_at=1 domain=x lock=acq.lock\n")
    lock, state, _ = acquire_ownership(str(lf))
    try:
        assert state == S.STALE_RECOVERED and lock.held     # acquired despite live pid text
    finally:
        lock.release()


def test_windows_dead_pid_semantics_no_longer_block(tmp_path, monkeypatch):
    # Simulate Windows os.kill(pid, 0) on a dead pid: OSError (winerror 87), which the
    # OLD PID-file lock mis-read as "alive". The fix uses NO liveness probe, so a
    # leftover artifact self-heals regardless of os.kill semantics.
    def _win_dead_kill(pid, sig):
        raise OSError(22, "Windows: OpenProcess failed for nonexistent pid")
    monkeypatch.setattr(os, "kill", _win_dead_kill)
    lf = tmp_path / "acq.lock"
    lf.write_text("pid=4242 host=oldbox started_at=1 domain=x lock=acq.lock\n")
    lock, state, _ = acquire_ownership(str(lf))
    try:
        assert state == S.STALE_RECOVERED and lock.held     # would have been refused before
    finally:
        lock.release()


# ============================================================================
# CONFIGURED-PATH FIDELITY — the lock stays where the operator configured it
# ============================================================================
def test_lock_path_matches_configured_file(tmp_path):
    lf = tmp_path / "sub" / "calendar_acq.lock"
    lock = NewsAcquisitionLock(str(lf)).acquire()   # creates the dir + lock file
    try:
        assert lock.path == lf.resolve()            # exactly where the operator configured
        assert lock.path.name == "calendar_acq.lock"
        assert lf.exists()
    finally:
        lock.release()


def test_same_file_two_instances_contend(tmp_path):
    # backward-compat with the historical duplicate-block test, via the new primitive
    lf = tmp_path / "acq.lock"
    a = NewsAcquisitionLock(str(lf)).acquire()
    try:
        with pytest.raises(NewsAcquisitionLockHeld):
            NewsAcquisitionLock(str(lf)).acquire()
    finally:
        a.release()


# ============================================================================
# MULTIPROCESS — real cross-process ownership + crash self-heal (production model)
# ============================================================================
def _mp_acquire_hold(lock_path, ready_evt, release_evt, result_q):
    from forex_swing_orb.newsfeed.acquisition_lock import acquire_ownership as _acq
    lock, state, _ = _acq(lock_path)
    if lock is None:
        result_q.put(("refused", state))
        return
    result_q.put(("owned", state))
    ready_evt.set()
    release_evt.wait(10)
    lock.release()


def _mp_acquire_then_die(lock_path, ready_evt):
    # Acquire and then EXIT WITHOUT releasing (simulates crash / forced kill / power
    # loss). The kernel must free the OS lock on process death.
    from forex_swing_orb.newsfeed.acquisition_lock import acquire_ownership as _acq
    lock, state, _ = _acq(lock_path)
    assert lock is not None
    ready_evt.set()
    os._exit(0)                                     # no release(), no atexit, no cleanup


def _mp_ctx():
    import multiprocessing as mp
    return mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()


def test_1_multiprocess_single_owner(tmp_path):
    ctx = _mp_ctx()
    lp = str(tmp_path / "acq.lock")
    ready = ctx.Event(); release = ctx.Event(); q = ctx.Queue()
    a = ctx.Process(target=_mp_acquire_hold, args=(lp, ready, release, q))
    a.start()
    assert ready.wait(10), "process A did not acquire"
    assert q.get(timeout=10) == ("owned", S.ACQUIRED)
    # B tries the same domain while A LIVES -> must be refused (exactly one owner)
    ready_b = ctx.Event(); q_b = ctx.Queue()
    b = ctx.Process(target=_mp_acquire_hold, args=(lp, ready_b, release, q_b))
    b.start(); b.join(10)
    kind, state = q_b.get(timeout=10)
    assert kind == "refused" and state == S.HELD_BY_OTHER
    release.set(); a.join(10)


def test_2_process_death_self_heals_ownership(tmp_path):
    # The reported scenario: an acquisition process dies WITHOUT releasing (no
    # python.exe left), then Session Edge restarts. Startup must self-heal.
    ctx = _mp_ctx()
    lp = str(tmp_path / "acq.lock")
    ready = ctx.Event()
    dead = ctx.Process(target=_mp_acquire_then_die, args=(lp, ready))
    dead.start()
    assert ready.wait(10), "the crashing owner did not acquire"
    dead.join(10)
    assert dead.exitcode == 0
    assert Path(lp).exists()                        # a leftover artifact remains on disk
    # restart: no live owner exists -> acquire succeeds (STALE_RECOVERED), never blocks
    lock, state, _ = acquire_ownership(lp)
    try:
        assert lock is not None and state == S.STALE_RECOVERED
    finally:
        lock.release()


# ============================================================================
# SERVICE + ENTRYPOINT — truthful state, health field, exit codes
# ============================================================================
from forex_swing_orb.newsfeed.config import CalendarConfig  # noqa: E402
from forex_swing_orb.newsfeed.contract import RawCalendar  # noqa: E402
from forex_swing_orb.newsfeed.acquire import CalendarAcquirer  # noqa: E402
from forex_swing_orb.newsfeed.provider import InjectableCalendarProvider  # noqa: E402
from forex_swing_orb.newsfeed.service import CalendarAcquisitionService  # noqa: E402


def _raw():
    return RawCalendar(source_name="t", source_identifier="t.json", provider_version="v1",
                       fetched_at=NOW, events=(), source_as_of=NOW, complete=True,
                       trusted=True)


def _svc(tmp_path, *, lock_file, enabled=True):
    out = tmp_path / "news.json"
    health = tmp_path / "calendar_acq_status.json"
    cfg = CalendarConfig(enabled=enabled, provider="static", output_file=str(out),
                         health_file=str(health), refresh_sec=10, retries=0,
                         backoff_sec=0, lock_file=lock_file)
    prov = InjectableCalendarProvider(lambda now: _raw(), trusted=True)
    svc = CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                     now_fn=lambda: NOW, sleep_fn=lambda s: None)
    return svc, out, health


def test_service_reports_acquired_and_records_health(tmp_path):
    svc, out, health = _svc(tmp_path, lock_file=str(tmp_path / "acq.lock"))
    state = svc.run_forever(max_cycles=1)
    assert state == S.ACQUIRED and svc.acquisition_owner == S.ACQUIRED
    import json
    hs = json.loads(health.read_text(encoding="utf-8"))
    assert hs["acquisition_owner"] == S.ACQUIRED          # observational field present
    assert "status" in hs and "healthy" in hs            # separate dimensions intact


def test_service_stale_recovered_after_leftover(tmp_path):
    lf = tmp_path / "acq.lock"
    lf.write_text("pid=999999 host=old started_at=1 domain=x lock=acq.lock\n")
    svc, out, health = _svc(tmp_path, lock_file=str(lf))
    state = svc.run_forever(max_cycles=1)
    assert state == S.STALE_RECOVERED
    import json
    hs = json.loads(health.read_text(encoding="utf-8"))
    assert hs["acquisition_owner"] == S.STALE_RECOVERED


def test_service_refuses_when_live_owner_holds(tmp_path):
    lf = tmp_path / "acq.lock"
    holder = NewsAcquisitionLock(str(lf)).acquire()
    try:
        svc, out, health = _svc(tmp_path, lock_file=str(lf))
        state = svc.run_forever(max_cycles=1)
        assert state == S.HELD_BY_OTHER
        assert not out.exists()                          # never ran a refresh cycle
    finally:
        holder.release()


def test_service_disabled_has_no_owner(tmp_path):
    svc, out, _ = _svc(tmp_path, lock_file=str(tmp_path / "acq.lock"), enabled=False)
    assert svc.run_forever(max_cycles=1) is None
    assert svc.acquisition_owner is None and not out.exists()


def test_entrypoint_exit_code_4_when_held(tmp_path, monkeypatch):
    from forex_swing_orb.newsfeed import __main__ as M
    lf = tmp_path / "acq.lock"
    holder = NewsAcquisitionLock(str(lf)).acquire()
    try:
        svc, _, _ = _svc(tmp_path, lock_file=str(lf))
        monkeypatch.setattr(M, "build_from_env", lambda: svc)
        assert M.main([]) == 4                           # fail-closed refusal, not 0
    finally:
        holder.release()


def test_entrypoint_exit_code_0_when_owner(tmp_path, monkeypatch):
    from forex_swing_orb.newsfeed import __main__ as M
    svc, _, _ = _svc(tmp_path, lock_file=str(tmp_path / "acq.lock"))
    # bound the loop so the entrypoint returns
    orig = svc.run_forever
    monkeypatch.setattr(svc, "run_forever", lambda: orig(max_cycles=1))
    monkeypatch.setattr(M, "build_from_env", lambda: svc)
    assert M.main([]) == 0
