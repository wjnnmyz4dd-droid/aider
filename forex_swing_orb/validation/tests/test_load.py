"""Phase 3A - load / stress validation.

Drives 1,000 / 5,000 / 10,000 deterministic signals through the full pipeline and
measures throughput, latency, memory, disk, restart-recovery time, dedup-lookup
time and bridge-scan time. Correctness invariants are asserted at every scale:
every signal executes exactly once, exactly one result each, no duplicate orders.

Metrics are printed (run with -s) and appended to a JSON sink for the report.
"""

from __future__ import annotations

import json
import os
import time
import tracemalloc
from pathlib import Path

import pytest

from forex_swing_orb.bridge.contract import ResultState
from forex_swing_orb.validation import harness as H

NOW = H.NOW
SINK = Path(os.environ.get("SE_LOAD_SINK", "/tmp/se_load_metrics.jsonl"))


def _record(metrics):
    try:
        with open(SINK, "a", encoding="utf-8") as f:
            f.write(json.dumps(metrics, sort_keys=True) + "\n")
    except OSError:
        pass
    print("LOADMETRIC " + json.dumps(metrics, sort_keys=True))


@pytest.mark.parametrize("n", [1000, 5000, 10000])
def test_load(tmp_path, n):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    recs = [H.make_instruction(i=i) for i in range(n)]

    t0 = time.perf_counter()
    for r in recs:
        H.produce(paths, r, now=NOW)
    produce_s = time.perf_counter() - t0

    # bridge scan time: one enumeration pass over pending with n files
    t = time.perf_counter()
    _ = sorted(p.name for p in paths.pending.iterdir())
    scan_s = time.perf_counter() - t

    # dedup lookup: average resolve() over a sample of unseen ids
    sample = [recs[i]["signal_id"] for i in range(0, n, max(1, n // 200))]
    t = time.perf_counter()
    for sid in sample:
        ec.resolver.resolve(sid)
    dedup_us = (time.perf_counter() - t) / len(sample) * 1e6

    tracemalloc.start()
    t0 = time.perf_counter()
    results = H.drain(ec, now=NOW)
    drain_s = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    disk = H.disk_usage(paths)

    # restart-recovery time: cold reopen + reconstruct (scan + ticket rebuild)
    ec2, _, _ = H.reopen(paths, mt5)
    t0 = time.perf_counter()
    ec2.recover(NOW)
    recover_s = time.perf_counter() - t0

    # correctness at scale
    assert len(results) == n
    assert all(r["status"] == ResultState.EXECUTED for r in results)
    assert len(mt5.order_log) == n
    assert H.count_files(paths.results) == n
    assert len(mt5.positions) == n
    # no duplicate orders: every comment (signal_id) is unique
    comments = [o["comment"] for o in mt5.order_log]
    assert len(set(comments)) == n

    _record({
        "signals": n,
        "produce_s": round(produce_s, 4),
        "drain_s": round(drain_s, 4),
        "throughput_per_s": round(n / drain_s, 1),
        "latency_ms": round(drain_s / n * 1000, 4),
        "peak_mem_mb": round(peak / 1e6, 2),
        "disk_bytes": disk,
        "disk_per_signal_b": round(disk / n, 1),
        "recover_s": round(recover_s, 4),
        "dedup_lookup_us": round(dedup_us, 2),
        "bridge_scan_s": round(scan_s, 4),
    })
