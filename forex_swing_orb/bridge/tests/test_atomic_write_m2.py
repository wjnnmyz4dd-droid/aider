"""M-2 atomic-write temp-file collision hardening (PR-3M2).

The shared generic atomic writer (bridge.atomic.atomic_write_text) must give every
write attempt its OWN unique temporary file in the destination directory, so two
writers targeting the SAME destination can never share a temp path, write into each
other's temp, clean up each other's temp, or produce a torn/failed replace. The
destination must still become visible atomically (last successful replace wins).

Deterministic (barrier-synchronized threads + a real multiprocessing case); no
probabilistic timing. No networking; no real MT5.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest import mock

import pytest

from forex_swing_orb.bridge.atomic import atomic_write_text


# ============================================================================
# B / REPRODUCTION — a barrier that forces the unsafe interleaving
# ============================================================================
def _two_writer_race(tmp_path, payload_a, payload_b):
    """Run writers A and B against the same destination. A is paused immediately
    before its os.replace (its temp already written+fsynced); B then runs to
    completion; finally A is released. Returns (results, dest_content, leftovers)."""
    dest = tmp_path / "dest.json"
    a_at_replace = threading.Event()
    let_a_go = threading.Event()
    results = {}
    real_replace = os.replace

    def patched_replace(src, dst):
        if threading.current_thread().name == "W-A":
            a_at_replace.set()
            let_a_go.wait(5)
        return real_replace(src, dst)

    def write(name, payload):
        try:
            atomic_write_text(dest, payload)
            results[name] = "ok"
        except BaseException as exc:                 # capture the failure classification
            results[name] = type(exc).__name__

    with mock.patch("os.replace", patched_replace):
        ta = threading.Thread(target=write, args=("W-A", payload_a), name="W-A")
        tb = threading.Thread(target=write, args=("W-B", payload_b), name="W-B")
        ta.start()
        assert a_at_replace.wait(5)                  # A wrote+fsynced its temp, at replace
        tb.start(); tb.join(5)                       # B runs fully
        let_a_go.set()                               # release A to replace
        ta.join(5)
    leftovers = list(tmp_path.glob(".*.tmp"))
    return results, (dest.read_text(encoding="utf-8") if dest.exists() else None), leftovers


def test_m2_concurrent_same_destination_both_succeed_no_tear(tmp_path):
    # Under the OLD fixed-temp implementation this FAILS: B truncates+consumes the
    # shared temp, so A's os.replace hits FileNotFoundError. Under the fixed
    # unique-temp implementation both writers own separate temps and both succeed.
    payload_a, payload_b = "A" * 5000, "B" * 3000
    results, content, leftovers = _two_writer_race(tmp_path, payload_a, payload_b)
    assert results.get("W-A") == "ok", f"writer A failed (M-2): {results}"
    assert results.get("W-B") == "ok", f"writer B failed (M-2): {results}"
    # destination is exactly ONE complete payload — never torn, never mixed
    assert content in (payload_a, payload_b)
    assert content != "" and content is not None
    assert not leftovers                            # no orphan temp after success


# ============================================================================
# N — CONCURRENCY MATRIX (deterministic barrier, all writers released together)
# ============================================================================
def _fan_in_writers(tmp_path, payloads):
    """N writers to one destination, all released from a barrier simultaneously.
    Returns (results, final_content, leftovers)."""
    dest = tmp_path / "dest.json"
    n = len(payloads)
    barrier = threading.Barrier(n)
    results = {}
    lock = threading.Lock()

    def write(i, payload):
        barrier.wait(5)
        try:
            atomic_write_text(dest, payload)
            r = "ok"
        except BaseException as exc:
            r = type(exc).__name__
        with lock:
            results[i] = r

    threads = [threading.Thread(target=write, args=(i, p)) for i, p in enumerate(payloads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    leftovers = list(tmp_path.glob(".*.tmp"))
    return results, (dest.read_text(encoding="utf-8") if dest.exists() else None), leftovers


def test_1_two_writers_unique_temps(tmp_path):
    results, content, leftovers = _fan_in_writers(tmp_path, ["alpha", "beta"])
    assert all(v == "ok" for v in results.values())
    assert content in ("alpha", "beta")
    assert not leftovers


def test_2_ten_writers_same_destination(tmp_path):
    payloads = [f"payload-{i}-" + str(i) * (10 + i) for i in range(10)]
    results, content, leftovers = _fan_in_writers(tmp_path, payloads)
    assert all(v == "ok" for v in results.values()), results
    assert content in payloads                       # exactly one complete winner
    assert not leftovers


def test_3_concurrent_very_different_sizes(tmp_path):
    payloads = ["x" * 1, "y" * 200_000, "z" * 50]
    results, content, leftovers = _fan_in_writers(tmp_path, payloads)
    assert all(v == "ok" for v in results.values()), results
    assert content in payloads                       # never a size-mixed/torn blob
    assert not leftovers


def test_4_5_6_concurrent_json_payloads_complete(tmp_path):
    from forex_swing_orb.bridge import serialize
    payloads = [serialize.canonical_json({"w": i, "data": [i] * (i + 1)}) for i in range(8)]
    results, content, leftovers = _fan_in_writers(tmp_path, payloads)
    assert all(v == "ok" for v in results.values()), results
    ok, obj = serialize.loads(content)               # must parse -> not torn
    assert ok and content in payloads
    assert not leftovers


def test_7_no_filenotfound_from_shared_temp(tmp_path):
    # the exact old-race failure: a shared temp caused FileNotFoundError on replace.
    results, _, _ = _two_writer_race(tmp_path, "AAAA", "BBBB")
    assert "FileNotFoundError" not in results.values()


def test_8_no_temp_left_after_success(tmp_path):
    for i in range(5):
        atomic_write_text(tmp_path / "d.json", f"v{i}")
    assert (tmp_path / "d.json").read_text(encoding="utf-8") == "v4"
    assert not list(tmp_path.glob(".*.tmp"))


def test_11_concurrent_different_destinations_independent(tmp_path):
    dests = [tmp_path / f"d{i}.json" for i in range(6)]
    barrier = threading.Barrier(len(dests))

    def write(d, payload):
        barrier.wait(5)
        atomic_write_text(d, payload)

    threads = [threading.Thread(target=write, args=(d, f"content-{i}"))
               for i, d in enumerate(dests)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    for i, d in enumerate(dests):
        assert d.read_text(encoding="utf-8") == f"content-{i}"
    assert not list(tmp_path.glob(".*.tmp"))


def test_12_repeated_writes_remain_atomic(tmp_path):
    d = tmp_path / "d.json"
    for i in range(50):
        atomic_write_text(d, f"iteration-{i}")
    assert d.read_text(encoding="utf-8") == "iteration-49"
    assert not list(tmp_path.glob(".*.tmp"))


# ============================================================================
# O — FAILURE INJECTION
# ============================================================================
def test_13_18_19_replace_failure_preserves_destination_and_cleans_temp(tmp_path):
    d = tmp_path / "d.json"
    atomic_write_text(d, "ORIGINAL")                 # a valid prior value
    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated replace failure")

    with mock.patch("os.replace", boom):
        with pytest.raises(OSError):
            atomic_write_text(d, "NEWVALUE")
    # destination retains the last COMPLETE value (never partial)
    assert d.read_text(encoding="utf-8") == "ORIGINAL"
    # this writer's temp was cleaned up (no orphan)
    assert not list(tmp_path.glob(".*.tmp"))


def test_15_fsync_failure_cleans_temp_and_propagates(tmp_path):
    d = tmp_path / "d.json"
    real_fsync = os.fsync

    def boom(fd):
        raise OSError("simulated fsync failure")

    with mock.patch("os.fsync", boom):
        with pytest.raises(OSError):
            atomic_write_text(d, "VALUE")
    assert not d.exists()                             # never became visible
    assert not list(tmp_path.glob(".*.tmp"))         # temp cleaned up


def test_20_exception_propagates_not_masked_by_cleanup(tmp_path):
    d = tmp_path / "d.json"

    def boom(src, dst):
        raise OSError("original replace error")

    with mock.patch("os.replace", boom):
        with pytest.raises(OSError, match="original replace error"):
            atomic_write_text(d, "VALUE")


# ============================================================================
# P — CROSS-PROCESS (real multiprocessing; threads alone are insufficient)
# ============================================================================
def _mp_writer(dest_str, payload, barrier):
    # module-level so it is picklable by multiprocessing on any start method.
    from forex_swing_orb.bridge.atomic import atomic_write_text as _w
    try:
        barrier.wait(10)
    except Exception:
        pass
    _w(Path(dest_str), payload)


def test_p_cross_process_same_destination(tmp_path):
    import multiprocessing as mp
    ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() \
        else mp.get_context()
    dest = tmp_path / "dest.json"
    payloads = [f"proc-{i}-" + str(i) * (100 + i) for i in range(6)]
    barrier = ctx.Barrier(len(payloads))
    procs = [ctx.Process(target=_mp_writer, args=(str(dest), p, barrier))
             for p in payloads]
    for p in procs:
        p.start()
    for p in procs:
        p.join(15)
    for p in procs:
        assert p.exitcode == 0                       # no process crashed on a shared temp
    content = dest.read_text(encoding="utf-8")
    assert content in payloads                        # exactly one complete winner
    assert not list(tmp_path.glob(".*.tmp"))          # no orphan temp across processes


# ============================================================================
# Q — SECURITY / PATH SAFETY
# ============================================================================
def test_q_temp_created_under_destination_parent(tmp_path):
    sub = tmp_path / "nested"; sub.mkdir()
    d = sub / "d.json"
    seen = {}
    import tempfile as _tf
    real_mkstemp = _tf.mkstemp

    def spy(*a, **kw):
        fd, name = real_mkstemp(*a, **kw)
        seen["dir"] = str(Path(name).parent)
        seen["name"] = Path(name).name
        return fd, name

    with mock.patch("forex_swing_orb.bridge.atomic.tempfile.mkstemp", spy):
        atomic_write_text(d, "V")
    assert seen["dir"] == str(sub)                   # same directory as destination
    assert seen["name"].endswith(".tmp")             # ignorable by consumers
    assert d.read_text(encoding="utf-8") == "V"
