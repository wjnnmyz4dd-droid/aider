"""Phase 3A - determinism validation.

Identical inputs (same instructions, same injected ``now``, fresh terminals with
the same fixed ticket counter) must produce byte-identical instructions, acks,
results, archives, ledger and audit - and identical reason codes and terminal
outcomes.
"""

from __future__ import annotations

import os

from forex_swing_orb.bridge.contract import ResultState
from forex_swing_orb.validation import harness as H

NOW = H.NOW


def snapshot(paths):
    """Map every file under bridge_root to its bytes, keyed by path RELATIVE to
    the root (so two runs in different tmp dirs are comparable)."""
    out = {}
    root = str(paths.root)
    for base, _dirs, files in os.walk(root):
        for f in files:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as fh:
                out[rel] = fh.read()
    return out


def run_once(tmp_path, n=12):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    recs = [H.make_instruction(i=i) for i in range(n)]
    for r in recs:
        H.produce(paths, r, now=NOW)
    results = H.drain(ec, now=NOW)
    return paths, results


def test_pipeline_is_byte_identical(tmp_path):
    a = tmp_path / "run_a"; b = tmp_path / "run_b"
    a.mkdir(); b.mkdir()
    paths_a, res_a = run_once(a)
    paths_b, res_b = run_once(b)

    snap_a, snap_b = snapshot(paths_a), snapshot(paths_b)
    assert set(snap_a) == set(snap_b), "same set of artifacts"
    diffs = [k for k in snap_a if snap_a[k] != snap_b[k]]
    assert not diffs, f"byte-identical artifacts; differing: {diffs}"


def test_reason_codes_and_outcomes_stable(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"; a.mkdir(); b.mkdir()
    _, res_a = run_once(a)
    _, res_b = run_once(b)
    key = lambda rs: [(r["signal_id"], r["status"], r["reason_code"]) for r in rs]
    assert key(res_a) == key(res_b)
    assert all(r["status"] == ResultState.EXECUTED for r in res_a)


def test_deterministic_ids_are_content_addressed(tmp_path):
    """result_id / ack_id depend only on (signal_id, terminal state) - never the
    wall clock - so re-deriving them is stable."""
    from forex_swing_orb.bridge import serialize
    sid = H.signal_id(3)
    assert serialize.result_id(sid, ResultState.EXECUTED) == \
        serialize.result_id(sid, ResultState.EXECUTED)
    assert serialize.result_id(sid, "ACK") == serialize.result_id(sid, "ACK")
    assert serialize.result_id(sid, ResultState.EXECUTED) != \
        serialize.result_id(sid, ResultState.EXECUTION_FAILED)
