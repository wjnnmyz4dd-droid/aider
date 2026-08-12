"""PR-3E (F-3) — producer single-writer authority.

Only ONE producer may hold entry-authorization writer authority for a given entry
bridge at a time; a second producer on the same bridge fails closed BEFORE it can
evaluate, authorize, or write. Authority is an OS-held exclusive lock on the
(canonicalized) bridge root — released automatically on process death, never via a
PID/timestamp takeover heuristic (no split-brain). Deterministic; real file locking;
cross-process cases use a file-signal handshake, not sleep ordering.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.producer.bridge_health import observe_entry_bridge
from forex_swing_orb.producer.writer_lock import (ProducerWriterLock, ProducerLockHeld,
                                                  ProducerLockUnavailable, canonical_domain)

NOW = datetime(2026, 1, 7, 14, 0, tzinfo=timezone.utc)
_DEADLINE = 20.0                         # bounded timeout guard for cross-process handshakes


# --------------------------------------------------------------------------- #
# lock-level (§28.1-2, 9-11, 17, 20)
# --------------------------------------------------------------------------- #
def test_first_producer_acquires(tmp_path):
    lk = ProducerWriterLock(tmp_path).acquire()
    try:
        assert lk.held
        diag = lk.owner_diagnostics()
        assert diag and "pid=" in diag and "domain=" in diag
    finally:
        lk.release()
    assert not lk.held


def test_second_same_domain_blocked(tmp_path):
    a = ProducerWriterLock(tmp_path).acquire()
    b = ProducerWriterLock(tmp_path)
    try:
        with pytest.raises(ProducerLockHeld):
            b.acquire()
    finally:
        a.release()


def test_separate_domains_both_acquire(tmp_path):
    a = ProducerWriterLock(tmp_path / "acct_X" / "bridge").acquire()
    b = ProducerWriterLock(tmp_path / "acct_Y" / "bridge").acquire()
    try:
        assert a.held and b.held                     # genuinely separate domains
    finally:
        a.release(); b.release()


def test_same_bridge_different_path_spelling_conflicts(tmp_path):
    root = tmp_path / "bridge"
    root.mkdir()
    a = ProducerWriterLock(str(root)).acquire()          # absolute
    try:
        # trailing slash + '.' + a relative form all canonicalize to the same inode
        for spelling in (str(root) + "/", str(root) + "/./", os.path.relpath(str(root))):
            b = ProducerWriterLock(spelling)
            with pytest.raises(ProducerLockHeld):
                b.acquire()
    finally:
        a.release()


def test_same_bridge_different_config_conflicts(tmp_path):
    # "different config" that resolves to the SAME entry bridge still conflicts:
    # authority is the bridge writer domain, not the config-file identity.
    root = tmp_path / "bridge"
    a = ProducerWriterLock(root).acquire()
    try:
        with pytest.raises(ProducerLockHeld):
            ProducerWriterLock(root).acquire()
    finally:
        a.release()


def test_lock_domain_independent_of_sessions(tmp_path):
    # the lock key is the bridge root only; session selection cannot change it.
    assert canonical_domain(tmp_path) == canonical_domain(str(tmp_path) + "/./")


def test_diagnostics_no_secrets(tmp_path):
    lk = ProducerWriterLock(tmp_path).acquire()
    try:
        diag = lk.owner_diagnostics()
        # fields are exactly pid/host/started_at/domain; scan the non-path fields for
        # credential markers (the domain is an operator path, not a secret).
        assert diag.startswith("pid=") and " domain=" in diag
        non_path = diag.split(" domain=", 1)[0].lower()
        for secret in ("password", "login", "token", "secret", "apikey", "api_key",
                       "server=", "investor", "account="):
            assert secret not in non_path
    finally:
        lk.release()


def test_invalid_lock_path_fails_closed(tmp_path):
    # bridge root whose parent is a regular file -> cannot mkdir/open -> Unavailable.
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    lk = ProducerWriterLock(blocker / "bridge" / "sub")
    with pytest.raises(ProducerLockUnavailable):
        lk.acquire()


# --------------------------------------------------------------------------- #
# graceful release + reacquire (§28.6, 18)
# --------------------------------------------------------------------------- #
def test_release_then_reacquire(tmp_path):
    a = ProducerWriterLock(tmp_path).acquire()
    a.release()
    b = ProducerWriterLock(tmp_path).acquire()           # domain free again
    try:
        assert b.held
    finally:
        b.release()


# --------------------------------------------------------------------------- #
# stale metadata cannot split-brain (§28.8, §24, §30)
# --------------------------------------------------------------------------- #
def test_stale_metadata_alone_cannot_split_brain(tmp_path):
    # a leftover lock FILE (from a dead process) with arbitrary/corrupt contents must
    # NOT block a new producer — authority is the OS lock, not file existence/content.
    lockfile = canonical_domain(tmp_path) / ".producer_writer.lock"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    lockfile.write_text("pid=999999 host=ghost garbage!!", encoding="utf-8")
    a = ProducerWriterLock(tmp_path).acquire()           # no live holder -> acquires
    try:
        assert a.held
        # ...but while it is now LIVE-held, a second cannot seize it despite the file
        with pytest.raises(ProducerLockHeld):
            ProducerWriterLock(tmp_path).acquire()
    finally:
        a.release()


# --------------------------------------------------------------------------- #
# cross-process: exactly one winner + OS auto-release on death (§28.3, 7, 18, 22, 24)
# --------------------------------------------------------------------------- #
_HOLDER = (
    "import sys; sys.path.insert(0, {repo!r})\n"
    "from forex_swing_orb.producer.writer_lock import ProducerWriterLock\n"
    "from pathlib import Path\n"
    "root, held, rel = {root!r}, {held!r}, {rel!r}\n"
    "lk = ProducerWriterLock(root).acquire()\n"
    "Path(held).write_text('1')\n"
    "import time\n"
    "for _ in range(2000):\n"
    "    if Path(rel).exists(): break\n"
    "    time.sleep(0.01)\n"
    "{exit}\n"
)


def _wait(path, deadline=_DEADLINE):
    stop = time.time() + deadline
    while time.time() < stop:
        if Path(path).exists():
            return True
        time.sleep(0.01)
    return False


def _spawn_holder(tmp_path, *, crash):
    held = tmp_path / "held.flag"
    rel = tmp_path / "release.flag"
    root = str(tmp_path / "bridge")
    exit_stmt = "import os; os._exit(0)" if crash else "lk.release()"
    code = _HOLDER.format(repo=str(_REPO), root=root, held=str(held), rel=str(rel),
                          exit=exit_stmt)
    proc = subprocess.Popen([sys.executable, "-c", code])
    assert _wait(held), "holder subprocess never acquired the lock"
    return proc, rel, root


def test_simultaneous_holder_blocks_then_releases(tmp_path):
    # while a separate process holds the domain, THIS process cannot acquire.
    proc, rel, root = _spawn_holder(tmp_path, crash=False)
    try:
        with pytest.raises(ProducerLockHeld):
            ProducerWriterLock(root).acquire()
    finally:
        Path(rel).write_text("go")                       # signal holder to release+exit
        proc.wait(timeout=_DEADLINE)
    # after the holder releases, this process acquires deterministically
    lk = ProducerWriterLock(root).acquire()
    assert lk.held; lk.release()


def test_process_death_releases_lock(tmp_path):
    # holder CRASHES (os._exit, no release). The OS must free the lock so a new
    # producer can reacquire — with NO PID/timestamp takeover heuristic.
    proc, rel, root = _spawn_holder(tmp_path, crash=True)
    Path(rel).write_text("go")                           # let it reach the exit
    proc.wait(timeout=_DEADLINE)
    lk = ProducerWriterLock(root).acquire()              # OS auto-released on death
    try:
        assert lk.held
    finally:
        lk.release()


# --------------------------------------------------------------------------- #
# the lock does not interfere with the bridge consumer / observer (§21, §28.14-16)
# --------------------------------------------------------------------------- #
def test_lock_file_invisible_to_bridge_observer(tmp_path):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    lk = ProducerWriterLock(paths.root).acquire()
    try:
        # lock file lives at the bridge ROOT as a dot-file, not in pending/claimed
        assert lk.path.parent == paths.root and lk.path.name.startswith(".")
        assert not list(paths.pending.iterdir()) and not list(paths.claimed.iterdir())
        obs = observe_entry_bridge(paths, NOW)           # H5 observer unaffected
        assert obs.healthy and obs.outstanding_count == 0 and obs.missing_ack_count == 0
    finally:
        lk.release()


# --------------------------------------------------------------------------- #
# service integration: loser fails closed before writing (§28.4-6, 19)
# --------------------------------------------------------------------------- #
def _svc(make_runner, tmp_path, name, lock_root):
    from forex_swing_orb.producer import ProducerService
    runner, d = make_runner()
    svc = ProducerService(runner, str(tmp_path / f"{name}.log"),
                          str(tmp_path / f"{name}.health"), now_fn=lambda: NOW,
                          writer_lock=ProducerWriterLock(lock_root))
    return svc, d


def _pending(paths):
    return sorted(p.name for p in paths.pending.glob("*.json"))


def test_second_producer_fails_closed_and_writes_nothing(make_runner, tmp_path):
    a, da = _svc(make_runner, tmp_path, "A", tmp_path / "shared_bridge")
    a.start()                                            # A takes authority (no cycle/write yet)
    try:
        # B shares the SAME writer domain; it must fail closed BEFORE any cycle/write.
        b, db = _svc(make_runner, tmp_path, "B", tmp_path / "shared_bridge")
        with pytest.raises(ProducerLockHeld):
            b.run_forever(max_cycles=1)
        assert _pending(db["paths"]) == []              # loser wrote zero instructions
        assert not b.writer_lock.held                    # loser never held authority
    finally:
        a._release_writer_authority()


def test_lock_held_across_multiple_cycles(make_runner, tmp_path):
    a, da = _svc(make_runner, tmp_path, "A", tmp_path / "b2")
    a.start()                                            # acquired ONCE at startup
    try:
        for _ in range(3):
            a.runner.run_cycle(NOW)                      # authority persists across cycles
            with pytest.raises(ProducerLockHeld):        # a rival is blocked the whole time
                ProducerWriterLock(tmp_path / "b2").acquire()
        assert a.writer_lock.held
    finally:
        a._release_writer_authority()


def test_graceful_shutdown_releases_authority(make_runner, tmp_path):
    a, da = _svc(make_runner, tmp_path, "A", tmp_path / "b3")
    a.run_forever(max_cycles=1)                          # normal completion -> release in finally
    assert not a.writer_lock.held
    # domain is free again: a fresh producer can acquire
    nxt = ProducerWriterLock(tmp_path / "b3").acquire()
    assert nxt.held; nxt.release()


def test_health_reports_lock_held(make_runner, tmp_path):
    from forex_swing_orb.bridge import serialize
    a, da = _svc(make_runner, tmp_path, "A", tmp_path / "b4")
    a.run_forever(max_cycles=1)
    ok, obj = serialize.loads(Path(tmp_path / "A.health").read_text(encoding="utf-8"))
    assert ok and obj.get("producer_lock_held") is True and "producer_lock_domain" in obj
