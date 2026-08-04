"""Deterministic regression tests for the Session Edge Filesystem Bridge.

Pure stdlib behaviour; no networking, no MT5, no broker. Timestamps are fixed
inputs so every outcome (result_id, audit) is reproducible.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import make_instruction


def _produce(bridge, paths, ins, now, audit=None):
    return bridge.write_instruction(paths, ins, now, audit=audit)


# --- serialization / digest -------------------------------------------------

def test_deterministic_serialization_and_digest(bridge):
    ins = make_instruction()
    r1 = bridge.serialize.with_integrity_digest(ins)
    r2 = bridge.serialize.with_integrity_digest(ins)
    assert bridge.serialize.dumps(r1) == bridge.serialize.dumps(r2)
    assert r1["integrity_digest"] == r2["integrity_digest"]
    assert bridge.serialize.verify_integrity_digest(r1)


def test_result_id_is_deterministic_no_randomness(bridge):
    # keyed on (signal_id, status) ONLY (F-C) -> stable across time
    a = bridge.serialize.result_id("a1b2c3d4e5f60718", "ACCEPTED")
    b = bridge.serialize.result_id("a1b2c3d4e5f60718", "ACCEPTED")
    assert a == b and len(a) == 16 and all(c in "0123456789abcdef" for c in a)
    assert bridge.serialize.result_id("a1b2c3d4e5f60718", "REJECTED") != a


# --- atomic write / partial-write resistance --------------------------------

def test_atomic_write_visibility_no_tmp(bridge, wired, now):
    paths, _, audit, _ = wired
    dest = _produce(bridge, paths, make_instruction(), now, audit=audit)
    assert dest.exists() and dest.name == "a1b2c3d4e5f60718.json"
    assert not any(p.name.endswith(".tmp") for p in paths.pending.iterdir())


def test_partial_write_tmp_is_ignored_by_claim(bridge, wired, now):
    paths, _, _, consumer = wired
    (paths.pending / ".deadbeefdeadbeef.json.tmp").write_text("{partial", encoding="utf-8")
    assert consumer.claim_next(now) is None   # a .tmp is never claimable


# --- happy path -------------------------------------------------------------

def test_happy_path_accept(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    sid = consumer.claim_next(now)
    assert sid == "a1b2c3d4e5f60718"
    result = consumer.process(sid, now)
    assert result["status"] == bridge.ResultState.ACCEPTED
    assert not list(paths.claimed.iterdir())                      # moved out of claimed
    assert (paths.archive_accepted / f"{sid}.json").exists()      # archived accepted
    assert any(p.name.startswith(sid) for p in paths.results.iterdir())  # one result
    assert ledger.is_seen(sid)                                    # ledger recorded


def test_result_has_no_execution_fields_populated(bridge, wired, now):
    paths, _, audit, consumer = wired
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    sid = consumer.claim_next(now)
    r = consumer.process(sid, now)
    assert r["broker_order_id"] is None and r["filled_price"] is None
    assert r["execution_error"] is None and r["compliance_decision"] is None


# --- claiming ---------------------------------------------------------------

def test_atomic_claim_single_owner(bridge, wired, now):
    paths, ledger, audit, c1 = wired
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    c2 = bridge.Consumer(paths, bridge.DEFAULT_CONFIG, ledger, audit)
    assert c1.claim("a1b2c3d4e5f60718", now) is True
    assert c2.claim("a1b2c3d4e5f60718", now) is False   # already claimed


def test_multiple_consumer_race_via_claim_next(bridge, wired, now):
    paths, ledger, audit, c1 = wired
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    c2 = bridge.Consumer(paths, bridge.DEFAULT_CONFIG, ledger, audit)
    got = [c1.claim_next(now), c2.claim_next(now)]
    assert got.count("a1b2c3d4e5f60718") == 1 and got.count(None) == 1


def test_no_lock_files_created(bridge, wired, now):
    paths, _, audit, consumer = wired
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    consumer.claim_next(now)
    for d in (paths.pending, paths.claimed):
        assert not any(p.suffix == ".lock" for p in d.iterdir())


# --- duplicate / idempotency ------------------------------------------------

def test_duplicate_detection_and_idempotency(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)
    # re-present the SAME signal_id later
    _produce(bridge, paths, make_instruction(), now, audit=audit)
    sid = consumer.claim_next(now)
    r2 = consumer.process(sid, now)
    assert r2["status"] == bridge.ResultState.DUPLICATE
    # re-presentation adopts the original terminal family (ACCEPTED) — no new/
    # conflicting artifact, and exactly one terminal result remains
    assert (paths.archive_accepted / f"{sid}.json").exists()
    assert len([p for p in paths.results.iterdir() if p.name.startswith(sid)]) == 1


# --- validation failures (fail closed) --------------------------------------

def _process_record(bridge, tmp_path, record_transform, now, cfg=None):
    """Write a crafted record straight into claimed/ and process it."""
    paths, ledger, audit, consumer = bridge.open_bridge(tmp_path, cfg or bridge.DEFAULT_CONFIG)
    ins = make_instruction()
    record = bridge.serialize.with_integrity_digest(ins)
    record = record_transform(record)
    (paths.claimed / f"{ins['signal_id']}.json").write_text(
        bridge.serialize.dumps(record), encoding="utf-8")
    return consumer.process(ins["signal_id"], now), paths


def test_expired_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["expiration_timestamp"] = bridge.serialize.iso_utc(now - timedelta(minutes=1))
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.EXPIRED and r["reason_code"] == bridge.ReasonCode.E_EXPIRED


def test_invalid_schema_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["schema_version"] = 99
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_SCHEMA


def test_unknown_strategy_version_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["strategy_version"] = "swing_orb.v9.9.9"
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_STRATEGY


def test_invalid_digest_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["entry_price"] = rec["entry_price"] + 0.001   # tamper AFTER digest
        return rec
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_INTEGRITY


def test_missing_field_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec.pop("risk_fraction")
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_FIELDS


def test_structural_geometry_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["stop_loss"] = rec["entry_price"] + 0.001   # LONG with stop above entry
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_STRUCT


def test_future_timestamp_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["generated_timestamp"] = bridge.serialize.iso_utc(now + timedelta(minutes=10))
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_FUTURE


def test_symbol_format_rejected(bridge, tmp_path, now):
    def xf(rec):
        rec["symbol"] = "EUR/USD"
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["status"] == bridge.ResultState.REJECTED and r["reason_code"] == bridge.ReasonCode.E_SYMBOL


def test_validation_stops_on_first_failure(bridge, tmp_path, now):
    # both bad-schema AND expired -> schema (step 2) wins over expiry (step 6)
    def xf(rec):
        rec["schema_version"] = 99
        rec["expiration_timestamp"] = bridge.serialize.iso_utc(now - timedelta(minutes=1))
        return bridge.serialize.with_integrity_digest(rec)
    r, _ = _process_record(bridge, tmp_path, xf, now)
    assert r["reason_code"] == bridge.ReasonCode.E_SCHEMA


def test_hook_failure_is_FAILED(bridge, tmp_path, now):
    def bad_hook(record, now):
        raise RuntimeError("boom")
    paths, ledger, audit, consumer = bridge.open_bridge(tmp_path, hook=bad_hook)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    r = consumer.process(consumer.claim_next(now), now)
    assert r["status"] == bridge.ResultState.FAILED and r["reason_code"] == bridge.ReasonCode.E_HOOK


# --- quarantine -------------------------------------------------------------

def test_corrupt_json_quarantined(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    sid = "a1b2c3d4e5f60718"
    (paths.claimed / f"{sid}.json").write_text("{not valid json", encoding="utf-8")
    r = consumer.process(sid, now)
    assert r is None
    assert (paths.quarantine / f"{sid}.json").exists()
    assert not list(paths.results.iterdir())        # no result for an unparseable file


def test_oversized_quarantined(bridge, tmp_path, now):
    cfg = bridge.BridgeConfig(max_instruction_bytes=10)
    paths, ledger, audit, consumer = bridge.open_bridge(tmp_path, cfg)
    sid = "a1b2c3d4e5f60718"
    (paths.claimed / f"{sid}.json").write_text(bridge.serialize.dumps(
        bridge.serialize.with_integrity_digest(make_instruction())), encoding="utf-8")
    assert consumer.process(sid, now) is None
    assert (paths.quarantine / f"{sid}.json").exists()


def test_unsafe_basename_quarantined_on_reconcile(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    (paths.pending / "not-a-valid-name.json").write_text("{}", encoding="utf-8")
    summary = bridge.recover(consumer, now)
    assert summary["pending_quarantined"] == 1
    assert (paths.quarantine / "not-a-valid-name.json").exists()


# --- restart recovery -------------------------------------------------------

def test_restart_reprocess_claimed_not_terminal(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.claim_next(now)                 # crash before process: file stuck in claimed
    summary = bridge.recover(consumer, now)
    assert summary["claimed_reprocessed"] == 1
    assert (paths.archive_accepted / "a1b2c3d4e5f60718.json").exists()


def test_restart_archives_terminal_without_reprocess(bridge, wired, now):
    # power-loss between result-write+ledger and the archive move
    paths, ledger, audit, consumer = wired
    ins = make_instruction()
    bridge.write_instruction(paths, ins, now, audit=audit)
    consumer.claim(ins["signal_id"], now)
    ledger.record(ins["signal_id"], bridge.ResultState.ACCEPTED, "0000111122223333",
                  bridge.serialize.iso_utc(now))   # terminal, but file still in claimed
    n_results_before = len(list(paths.results.iterdir()))
    summary = bridge.recover(consumer, now)
    assert summary["claimed_adopted"] == 1 and summary["claimed_reprocessed"] == 0
    assert (paths.archive_accepted / f"{ins['signal_id']}.json").exists()
    assert len(list(paths.results.iterdir())) == n_results_before   # NOT reprocessed


def test_restart_cleans_tmp(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    (paths.pending / ".abcd.json.tmp").write_text("partial", encoding="utf-8")
    summary = bridge.recover(consumer, now)
    assert summary["tmp_cleaned"] >= 1
    assert not any(p.name.endswith(".tmp") for p in paths.pending.iterdir())


def test_restart_persistent_dedup(bridge, tmp_path, now):
    paths, ledger, audit, consumer = bridge.open_bridge(tmp_path)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)
    # simulate a fresh process: brand-new ledger loaded from disk
    ledger2 = bridge.DedupLedger(paths.dedup_ledger)
    assert ledger2.is_seen("a1b2c3d4e5f60718")   # survived restart


def test_no_double_processing_after_restart(bridge, tmp_path, now):
    paths, ledger, audit, consumer = bridge.open_bridge(tmp_path)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)
    # re-present same id, fresh ledger (restart), process again
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    ledger2 = bridge.DedupLedger(paths.dedup_ledger)
    consumer2 = bridge.Consumer(paths, bridge.DEFAULT_CONFIG, ledger2, audit)
    r = consumer2.process(consumer2.claim_next(now), now)
    assert r["status"] == bridge.ResultState.DUPLICATE


# --- audit / directory recovery ---------------------------------------------

def test_audit_generation(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)
    actions = {a["action"] for a in audit.read_all()}
    assert {"produce", "claim", "process"} <= actions


def test_directory_recovery(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    import shutil
    shutil.rmtree(paths.quarantine)
    paths.ensure()                       # idempotent recreate
    assert paths.quarantine.is_dir()


# --- filesystem safety ------------------------------------------------------

def test_filesystem_safe_filenames_hex_only(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)
    for d in (paths.results, paths.archive_accepted):
        for p in d.iterdir():
            assert "/" not in p.name
            assert all(c in "0123456789abcdef." + "json" for c in p.name)


# --- static boundary checks (no networking / no MT5) ------------------------

def _bridge_import_roots(bridge):
    roots = set()
    pkg_dir = Path(bridge.__file__).resolve().parent
    for py in pkg_dir.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    roots.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    roots.add((node.module or "").split(".")[0])
    return roots


def test_no_networking_imports(bridge):
    forbidden = {"socket", "urllib", "http", "requests", "httpx", "aiohttp",
                 "ftplib", "smtplib", "telnetlib", "ssl", "websockets", "asyncio",
                 "xmlrpc", "ftp"}
    assert not (_bridge_import_roots(bridge) & forbidden)


def test_no_mt5_broker_titan_phantom_imports(bridge):
    roots = {r.lower() for r in _bridge_import_roots(bridge)}
    assert not ({"metatrader5", "mt5", "titan", "phantom"} & roots)


def test_bridge_is_stdlib_only(bridge):
    # bridge depends only on the stdlib (+ its own package) — no third-party
    roots = _bridge_import_roots(bridge)
    stdlib = {"os", "re", "json", "hashlib", "math", "datetime", "pathlib",
              "dataclasses", "", "__future__", "typing", "sys", "shutil", "stat"}
    assert roots <= stdlib, f"unexpected imports: {roots - stdlib}"


# --- F-C: crash-safe exactly-one terminal result ----------------------------

def test_crash_between_result_and_ledger_then_adopt(bridge, wired, now):
    from forex_swing_orb.bridge.contract import build_result
    paths, ledger, audit, consumer = wired
    ins = make_instruction()
    bridge.write_instruction(paths, ins, now, audit=audit)
    sid = consumer.claim_next(now)
    # simulate _finish partial: result WRITTEN, then CRASH (no ledger, no archive)
    rid = bridge.serialize.result_id(sid, bridge.ResultState.ACCEPTED)
    res = build_result(sid, rid, bridge.ResultState.ACCEPTED, bridge.ReasonCode.OK,
                       bridge.serialize.iso_utc(now), bridge.serialize.iso_utc(now), instruction=ins)
    consumer._write_result(res)
    # recovery with a counting hook and a FRESH ledger (as after a restart)
    calls = []
    def hook(record, n):
        calls.append(record["signal_id"]); return bridge.ResultState.ACCEPTED, bridge.ReasonCode.OK, {}
    ledger2 = bridge.DedupLedger(paths.dedup_ledger)
    c2 = bridge.Consumer(paths, bridge.DEFAULT_CONFIG, ledger2, audit, hook=hook)
    summary = bridge.recover(c2, now)
    results = [p for p in paths.results.iterdir() if p.name.startswith(sid)]
    assert len(results) == 1                 # exactly one terminal result
    assert summary["claimed_adopted"] == 1
    assert calls == []                       # hook NOT invoked again
    assert ledger2.is_seen(sid)              # ledger repaired deterministically
    assert (paths.archive_accepted / f"{sid}.json").exists()   # archive consistent


# --- F-D: dedup survives ledger loss ----------------------------------------

def test_ledger_loss_with_archive_evidence_rejects_duplicate(bridge, wired, now):
    import os
    paths, ledger, audit, consumer = wired
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)     # ACCEPTED, archived, ledger
    os.remove(paths.dedup_ledger)                       # lose the ledger entirely
    calls = []
    def hook(r, n):
        calls.append(1); return bridge.ResultState.ACCEPTED, bridge.ReasonCode.OK, {}
    ledger2 = bridge.DedupLedger(paths.dedup_ledger)
    c2 = bridge.Consumer(paths, bridge.DEFAULT_CONFIG, ledger2, audit, hook=hook)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)   # re-present
    r = c2.process(c2.claim_next(now), now)
    assert r["status"] == bridge.ResultState.DUPLICATE  # on-disk archive evidence caught it
    assert calls == []                                  # hook not re-invoked
    assert ledger2.is_seen("a1b2c3d4e5f60718")          # ledger rebuilt from disk


def test_ledger_loss_with_inbox_result_only(bridge, wired, now):
    import os
    paths, ledger, audit, consumer = wired
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.process(consumer.claim_next(now), now)
    os.remove(paths.dedup_ledger)
    (paths.archive_accepted / "a1b2c3d4e5f60718.json").unlink()   # keep ONLY inbox result
    ledger2 = bridge.DedupLedger(paths.dedup_ledger)
    c2 = bridge.Consumer(paths, bridge.DEFAULT_CONFIG, ledger2, audit)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    r = c2.process(c2.claim_next(now), now)
    assert r["status"] == bridge.ResultState.DUPLICATE


def test_conflicting_persistent_evidence_fails_closed(bridge, wired, now):
    from forex_swing_orb.bridge.contract import build_result
    paths, ledger, audit, consumer = wired
    sid = "a1b2c3d4e5f60718"
    (paths.archive_accepted / f"{sid}.json").write_text("{}", encoding="utf-8")   # ACCEPTED family
    rej = build_result(sid, bridge.serialize.result_id(sid, bridge.ResultState.REJECTED),
                       bridge.ResultState.REJECTED, bridge.ReasonCode.E_STRUCT,
                       bridge.serialize.iso_utc(now), bridge.serialize.iso_utc(now))
    (paths.results / f"{sid}.{rej['result_id']}.json").write_text(
        bridge.serialize.dumps(rej), encoding="utf-8")                             # REJECTED family
    (paths.claimed / f"{sid}.json").write_text(
        bridge.serialize.dumps(bridge.serialize.with_integrity_digest(make_instruction())), encoding="utf-8")
    r = consumer.process(sid, now)
    assert r is None
    assert (paths.quarantine / f"{sid}.json").exists()
    assert any(a["reason_code"] == bridge.ReasonCode.E_CONFLICT for a in audit.read_all())


# --- F-S: hook posture governs reconcile re-invocation ----------------------

def test_non_idempotent_hook_not_reinvoked_by_reconcile(bridge, tmp_path, now):
    calls = []
    def exec_hook(record, n):
        calls.append(record["signal_id"]); return bridge.ResultState.ACCEPTED, bridge.ReasonCode.OK, {}
    paths, ledger, audit, consumer = bridge.open_bridge(
        tmp_path, hook=exec_hook, hook_posture=bridge.HookPosture.NON_IDEMPOTENT_EXECUTION)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.claim_next(now)                     # CRASH before process (non-terminal)
    summary = bridge.recover(consumer, now)
    assert calls == []                                          # never blindly re-invoked
    assert summary["claimed_reconciliation_required"] == 1
    assert not list(paths.results.iterdir())                    # no duplicate terminal result
    assert (paths.claimed / "a1b2c3d4e5f60718.json").exists()   # left for external reconciliation
    assert bridge.ReasonCode.RECONCILIATION_REQUIRED in {a["reason_code"] for a in audit.read_all()}


def test_validation_only_hook_reruns_on_reconcile(bridge, tmp_path, now):
    calls = []
    def vo_hook(record, n):
        calls.append(1); return bridge.ResultState.ACCEPTED, bridge.ReasonCode.OK, {}
    paths, ledger, audit, consumer = bridge.open_bridge(
        tmp_path, hook=vo_hook, hook_posture=bridge.HookPosture.VALIDATION_ONLY)
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)
    consumer.claim_next(now)
    bridge.recover(consumer, now)
    assert calls == [1]                          # re-run permitted only for re-runnable posture
    assert (paths.archive_accepted / "a1b2c3d4e5f60718.json").exists()


# --- F-A / F-1 / F-2 hardening ----------------------------------------------

def test_claim_refuses_existing_claimed_destination(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    sid = "a1b2c3d4e5f60718"
    (paths.claimed / f"{sid}.json").write_text('{"stranded":true}', encoding="utf-8")
    bridge.write_instruction(paths, make_instruction(), now, audit=audit)   # pending/<sid>
    assert consumer.claim(sid, now) is False                 # refused (no overwrite)
    assert '"stranded"' in (paths.claimed / f"{sid}.json").read_text(encoding="utf-8")
    assert (paths.pending / f"{sid}.json").exists()          # pending left intact


def test_initial_ledger_creation_persists(bridge, tmp_path, now):
    paths, ledger, audit, consumer = bridge.open_bridge(tmp_path)
    assert not paths.dedup_ledger.exists()
    ledger.record("a1b2c3d4e5f60718", bridge.ResultState.ACCEPTED, "0" * 16,
                  bridge.serialize.iso_utc(now))
    assert paths.dedup_ledger.exists()
    assert bridge.DedupLedger(paths.dedup_ledger).is_seen("a1b2c3d4e5f60718")


def test_failed_move_is_audited(bridge, wired, now):
    paths, ledger, audit, consumer = wired
    missing = paths.claimed / "deadbeefdeadbeef.json"        # source does not exist
    ok = consumer._move_or_audit(missing, paths.archive_accepted / missing.name,
                                 now, "archive", "deadbeefdeadbeef")
    assert ok is False
    assert any(a["reason_code"] == bridge.ReasonCode.E_MOVE for a in audit.read_all())
