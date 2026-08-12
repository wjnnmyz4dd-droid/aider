"""End-to-end validation harness (test-only).

Builds the real pipeline out of the accepted components and provides
deterministic instruction generation plus non-invasive failure injectors
(context managers that monkeypatch stdlib/component seams — never production
code). Deterministic: all timestamps and tickets are inputs or fixed counters.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

from ..bridge import serialize
from ..bridge.audit import AuditLog
from ..bridge.config import DEFAULT_CONFIG
from ..bridge.ledger import DedupLedger
from ..bridge.paths import BridgePaths
from ..bridge.producer import write_instruction
from ..ea_mt5 import mock_mt5
from ..ea_mt5.execution_consumer import ExecutionConsumer

NOW = datetime(2024, 1, 25, 12, 0, 0, tzinfo=timezone.utc)

# Deterministic broker symbol universe (canonical <base>.FX -> broker <base>).
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD",
           "NZDUSD", "EURGBP")


def make_mt5():
    m = mock_mt5.MockMT5()
    for s in SYMBOLS:
        m.add_symbol(s)
    return m


def build(tmp_path, mt5=None, default_volume=0.10):
    """Wire a fresh bridge tree + execution adapter over a mock terminal."""
    paths = BridgePaths(tmp_path).ensure()
    ledger = DedupLedger(paths.dedup_ledger)
    audit = AuditLog(paths.audit_log)
    mt5 = mt5 or make_mt5()
    ec = ExecutionConsumer(paths, DEFAULT_CONFIG, ledger, audit, mt5,
                           default_volume=default_volume)
    return ec, paths, ledger, audit, mt5


def reopen(paths, mt5, default_volume=0.10):
    """Simulate a process/EA restart: brand-new in-memory objects over the same
    on-disk bridge tree and the same (persistent) mock terminal."""
    ledger = DedupLedger(paths.dedup_ledger)
    audit = AuditLog(paths.audit_log)
    ec = ExecutionConsumer(paths, DEFAULT_CONFIG, ledger, audit, mt5,
                           default_volume=default_volume)
    return ec, ledger, audit


def signal_id(i):
    """Deterministic 16-hex signal id for the i-th synthetic signal."""
    return hashlib.sha256(f"session-edge-signal-{i}".encode()).hexdigest()[:16]


def make_instruction(i=0, signal_id_value=None, direction=None, symbol=None,
                     entry=1.10000, stop=None, target=None, now=NOW,
                     strategy_version="swing_orb.v1.4.0", schema_version=2,
                     generated=None, expiration=None, session_id="LONDON"):
    """A deterministic, valid engine-shaped instruction (WITHOUT digest)."""
    sid = signal_id_value or signal_id(i)
    direction = direction or ("LONG" if i % 2 == 0 else "SHORT")
    symbol = symbol or (SYMBOLS[i % len(SYMBOLS)] + ".FX")
    if stop is None:
        stop = entry - 0.0020 if direction == "LONG" else entry + 0.0020
    if target is None:
        target = entry + 0.0040 if direction == "LONG" else entry - 0.0040
    gen = generated or (now - timedelta(minutes=15))
    exp = expiration or (now + timedelta(minutes=30))
    return {
        "schema_version": schema_version,
        "signal_id": sid,
        "session_id": session_id,
        "strategy_id": "forex_swing_orb",
        "strategy_version": strategy_version,
        "symbol": symbol,
        "direction": direction,
        "entry_price": round(entry, 5),
        "stop_loss": round(stop, 5),
        "take_profit": round(target, 5),
        "risk_fraction": 0.0025,
        "generated_timestamp": serialize.iso_utc(gen),
        "expiration_timestamp": serialize.iso_utc(exp),
        "evidence_summary": {"trend_d1": "BULLISH", "trend_h4": "BULLISH"},
        "news_eligibility": {"mode": "VERIFIED", "active": True},
    }


def produce(paths, instruction, now=NOW, audit=None):
    """Write one instruction into outbox/pending (adds integrity_digest)."""
    return write_instruction(paths, instruction, now, audit=audit)


def drain(ec, now=NOW, limit=1_000_000):
    """Claim+process every pending instruction (single sweep semantics repeated
    until pending is empty). Returns the list of terminal result records."""
    out = []
    for _ in range(limit):
        sid = ec.claim_next(now)
        if sid is None:
            break
        out.append(ec.process(sid, now))
    return out


# -- disk / audit helpers ----------------------------------------------------
def disk_usage(paths):
    total = 0
    for root, _dirs, files in os.walk(paths.root):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def count_files(directory):
    try:
        return sum(1 for p in directory.iterdir() if p.is_file())
    except FileNotFoundError:
        return 0


# -- failure injectors (context managers; monkeypatch only) ------------------
@contextmanager
def fail_os_replace():
    """Simulate a crash/power-loss during an atomic write: os.replace raises, so
    only a .tmp remains (never a torn target)."""
    real = os.replace

    def boom(src, dst, *a, **k):
        raise OSError("injected: crash during atomic rename")
    with mock.patch("os.replace", side_effect=boom):
        yield


@contextmanager
def _fail_open_for_write(exc):
    """Patch the builtin ``open`` so any write/append open raises ``exc`` (reads
    pass through). Bridge writes go through ``atomic_write_text``/
    ``append_line_fsync``, both of which use the builtin ``open``."""
    import builtins
    real_open = builtins.open

    def guarded(file, mode="r", *a, **k):
        if any(c in mode for c in ("w", "a", "x", "+")):
            raise exc
        return real_open(file, mode, *a, **k)
    with mock.patch("builtins.open", side_effect=guarded):
        yield


@contextmanager
def fail_permission_on_write():
    """Simulate a filesystem permission error (EACCES) on any write."""
    with _fail_open_for_write(PermissionError("injected: EACCES on write")):
        yield


@contextmanager
def fail_disk_full_on_write():
    """Simulate ENOSPC on any write."""
    import errno
    with _fail_open_for_write(OSError(errno.ENOSPC, "injected: no space left")):
        yield


@contextmanager
def crash_after(target_obj, method_name):
    """Let ``method_name`` run once, then raise — simulating a crash immediately
    AFTER that step completes (before the next step)."""
    real = getattr(target_obj, method_name)
    state = {"done": False}

    def wrapper(*a, **k):
        r = real(*a, **k)
        state["done"] = True
        raise RuntimeError(f"injected: crash after {method_name}")
    with mock.patch.object(target_obj, method_name, side_effect=wrapper):
        yield state


@contextmanager
def crash_before(target_obj, method_name):
    """Raise instead of running ``method_name`` — simulating a crash just BEFORE
    that step."""
    def wrapper(*a, **k):
        raise RuntimeError(f"injected: crash before {method_name}")
    with mock.patch.object(target_obj, method_name, side_effect=wrapper):
        yield
