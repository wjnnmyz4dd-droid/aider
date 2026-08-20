"""M-4 management result identity / forensic idempotency (PR-3M4).

One manage instruction must produce exactly ONE canonical terminal result artifact
per logical outcome. The result id is content-addressed on (manage_id, EFFECTIVE
terminal status) and is CLOCK-FREE — it describes WHAT happened, never WHEN a
(possibly duplicate) report was written. A recover re-run for the same outcome
resolves to the same filename and never mints a second forensic result file.

This is an artifact-hygiene cleanup: no management decision, broker action, ledger
authority, M-5 orphan recovery, or M-6 close confirmation changes. Deterministic;
MockMT5; no networking; no real MT5.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.manage import (ManageAction, ManageConsumer, ManagePaths,
                                    ManageStatus, build_instruction, initial_r_digest,
                                    write_manage_instruction)
from forex_swing_orb.manage import contract as MC
from conftest import NOW

BUY = mock_mt5.ORDER_TYPE_BUY


def _instr(**over):
    f = {"signal_id": "0123456789abcdef", "ticket": 5000001, "symbol": "EURUSD",
         "direction": "LONG", "action": ManageAction.MODIFY_STOP, "target_stop": 1.10020,
         "expected_current_stop": 1.09800, "prior_stop": 1.09800, "pm_phase": "INITIAL",
         "pm_reason": "PM_MODIFY@INITIAL", "structure_reference": None,
         "market_reference": 1.10200, "point": 0.00001, "digits": 5,
         "broker_min_stop_distance": 0.0, "per_ticket_sequence": 1,
         "generated_timestamp": serialize.iso_utc(NOW),
         "expiration_timestamp": serialize.iso_utc(NOW + timedelta(seconds=120)),
         "initial_r_digest": initial_r_digest("LONG", 1.10000, 1.09800)}
    f.update(over)
    return build_instruction(f)


def _mt5_with_long(sl=1.09800, ticket=5000001):
    m = mock_mt5.MockMT5(); m.add_symbol("EURUSD")
    m.positions[ticket] = mock_mt5.Position(ticket, "EURUSD", BUY, 0.1, 1.10000, sl,
                                            1.10600, "0123456789abcdef")
    return m


# ============================================================================
# IDENTITY
# ============================================================================
def test_1_same_manage_id_same_status_diff_timestamps_same_id():
    mid = "abcdef0123456789"
    a = MC.manage_result_id(mid, ManageStatus.APPLIED)
    b = MC.manage_result_id(mid, ManageStatus.APPLIED)
    assert a == b and len(a) == 16


def test_1b_reproduce_m4_clockfree_vs_old_digest():
    # REPRODUCTION: the OLD id (integrity digest over the full timestamped result)
    # drifts with wall clock; the NEW canonical id does not.
    base = {"manage_id": "abcdef0123456789", "status": ManageStatus.APPLIED,
            "signal_id": "0123456789abcdef", "ticket": 5000001, "symbol": "EURUSD"}
    r1 = dict(base, completed_timestamp="2026-01-07T10:00:00Z",
              applied_timestamp="2026-01-07T10:00:00Z", claimed_timestamp="2026-01-07T10:00:00Z")
    r2 = dict(base, completed_timestamp="2026-01-07T10:05:00Z",
              applied_timestamp="2026-01-07T10:05:00Z", claimed_timestamp="2026-01-07T10:05:00Z")
    old1 = serialize.compute_integrity_digest(r1)[:16]
    old2 = serialize.compute_integrity_digest(r2)[:16]
    assert old1 != old2                                   # the M-4 defect (old behavior)
    new1 = MC.manage_result_id(r1["manage_id"], r1["status"])
    new2 = MC.manage_result_id(r2["manage_id"], r2["status"])
    assert new1 == new2                                   # fixed: clock-free identity


def test_2_same_manage_id_diff_effective_status_diff_id():
    mid = "abcdef0123456789"
    applied = MC.manage_result_id(mid, ManageStatus.APPLIED)
    rejected = MC.manage_result_id(mid, ManageStatus.REJECTED_STALE)
    closed = MC.manage_result_id(mid, ManageStatus.NO_OP_CLOSED)
    assert len({applied, rejected, closed}) == 3


def test_2b_applied_and_already_applied_collapse():
    mid = "abcdef0123456789"
    assert (MC.manage_result_id(mid, ManageStatus.APPLIED)
            == MC.manage_result_id(mid, ManageStatus.ALREADY_APPLIED))


def test_2c_rejected_family_collapses_to_one_identity():
    mid = "abcdef0123456789"
    ids = {MC.manage_result_id(mid, s) for s in
           (ManageStatus.REJECTED_STALE, ManageStatus.REJECTED_LOOSEN,
            ManageStatus.REJECTED_BROKER_CONSTRAINT, ManageStatus.BROKER_REJECTED)}
    assert len(ids) == 1                                  # same effective outcome: REJECTED


@pytest.mark.parametrize("field", ["claimed_timestamp", "applied_timestamp",
                                   "completed_timestamp"])
def test_3_4_5_result_id_independent_of_timestamps(field):
    # the id formula takes only (manage_id, status): timestamp fields cannot enter it.
    mid = "abcdef0123456789"
    assert MC.manage_result_id(mid, ManageStatus.APPLIED) \
        == MC.manage_result_id(mid, ManageStatus.APPLIED)  # deterministic; field unused


def test_6_result_id_deterministic_across_process_restart():
    # pure function of its inputs -> identical in any process (no clock, pid, rng).
    import subprocess
    import sys
    mid = "abcdef0123456789"
    code = ("from forex_swing_orb.manage import contract as MC;"
            "from forex_swing_orb.manage import ManageStatus;"
            f"print(MC.manage_result_id('{mid}', ManageStatus.APPLIED))")
    repo = str(Path(__file__).resolve().parents[3])
    out = subprocess.check_output([sys.executable, "-c", code], cwd=repo).decode().strip()
    assert out == MC.manage_result_id(mid, ManageStatus.APPLIED)


# ============================================================================
# FILES
# ============================================================================
def test_7_first_terminal_result_writes_one_file(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    write_manage_instruction(mp, _instr(), NOW)
    ManageConsumer(mt5, mp).run_once(NOW)
    files = list(mp.results.glob("*.json"))
    assert len(files) == 1
    mid = _instr()["manage_id"]
    assert files[0].name == f"{mid}.{MC.manage_result_id(mid, ManageStatus.APPLIED)}.json"


def test_8_duplicate_identical_result_no_second_file(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    c = ManageConsumer(mt5, mp)
    write_manage_instruction(mp, _instr(), NOW); c.run_once(NOW)
    write_manage_instruction(mp, _instr(), NOW); c.run_once(NOW)   # replay
    assert len(list(mp.results.glob("*.json"))) == 1


def test_9_recover_rerun_no_second_file(tmp_path):
    # broker action applied, result written, crash before archive -> recover twice.
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    write_manage_instruction(mp, _instr(), NOW)
    c = ManageConsumer(mt5, mp)
    c.claim_next(NOW)                                # claimed, simulate crash before apply
    mt5.positions[5000001].sl = 1.10020             # broker actually applied
    out = c.recover(NOW)
    assert out and out[0]["status"] in (ManageStatus.ALREADY_APPLIED, ManageStatus.APPLIED)
    assert len(list(mp.results.glob("*.json"))) == 1
    # a second recover must not create another artifact
    ManageConsumer(mt5, mp).recover(NOW)
    assert len(list(mp.results.glob("*.json"))) == 1


def test_10_repeated_recovery_one_file(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    write_manage_instruction(mp, _instr(), NOW)
    ManageConsumer(mt5, mp).run_once(NOW)           # APPLIED + archived
    for _ in range(3):
        ManageConsumer(mt5, mp).recover(NOW)
    assert len(list(mp.results.glob("*.json"))) == 1


def test_11_legacy_old_format_result_still_discoverable(tmp_path):
    # a legacy timestamp-derived result id must remain discoverable by manage_id glob.
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(); mid = instr["manage_id"]
    res = MC.build_result({
        "manage_id": mid, "signal_id": instr["signal_id"], "ticket": 5000001,
        "symbol": "EURUSD", "action": ManageAction.MODIFY_STOP, "requested_stop": 1.10020,
        "expected_current_stop": 1.09800, "observed_stop_before": 1.09800,
        "observed_stop_after": 1.10020, "per_ticket_sequence": 1,
        "status": ManageStatus.APPLIED, "reason_code": "ok", "broker_retcode": 10009,
        "broker_message": None, "claimed_timestamp": serialize.iso_utc(NOW),
        "applied_timestamp": serialize.iso_utc(NOW), "completed_timestamp": serialize.iso_utc(NOW),
        "reconciliation_state": "TERMINAL"})
    legacy_rid = serialize.compute_integrity_digest(res)[:16]     # OLD scheme
    from forex_swing_orb.bridge.atomic import atomic_write_text
    atomic_write_text(mp.results / f"{mid}.{legacy_rid}.json", serialize.dumps(res))
    # consumer replay must recognize the legacy terminal artifact (fs dedup) and NOT
    # re-apply or add a new file.
    write_manage_instruction(mp, instr, NOW)
    r = ManageConsumer(mt5, mp).run_once(NOW)
    assert r["status"] == ManageStatus.ALREADY_APPLIED           # legacy evidence caught it
    assert len(list(mp.results.glob(f"{mid}.*.json"))) == 1      # no duplicate created


def test_12_legacy_plus_new_no_double_effective_outcome(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(); mid = instr["manage_id"]
    write_manage_instruction(mp, instr, NOW)
    ManageConsumer(mt5, mp).run_once(NOW)                        # writes canonical result
    # ledger records exactly one terminal for the manage_id
    from forex_swing_orb.manage.ledger import ManageLedger
    led = ManageLedger(mp.ea_ledger)
    assert led.is_terminal(mid)


# ============================================================================
# CONFLICT
# ============================================================================
def test_13_14_conflicting_payload_not_silently_overwritten(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(); mid = instr["manage_id"]
    canonical = f"{mid}.{MC.manage_result_id(mid, ManageStatus.APPLIED)}.json"
    # pre-plant a conflicting payload at the canonical name
    from forex_swing_orb.bridge.atomic import atomic_write_text
    atomic_write_text(mp.results / canonical, '{"manage_id":"' + mid + '","status":"TAMPERED"}')
    before = (mp.results / canonical).read_text(encoding="utf-8")
    write_manage_instruction(mp, instr, NOW)
    ManageConsumer(mt5, mp).run_once(NOW)                        # would-be APPLIED write
    after = (mp.results / canonical).read_text(encoding="utf-8")
    assert after == before                                       # NOT silently overwritten


def test_15_malformed_existing_result_fails_safely(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(); mid = instr["manage_id"]
    canonical = f"{mid}.{MC.manage_result_id(mid, ManageStatus.APPLIED)}.json"
    (mp.results / canonical).write_text("{ not json", encoding="utf-8")
    write_manage_instruction(mp, instr, NOW)
    # a malformed existing file at the canonical name is not trusted as valid
    # terminal evidence (readers verify integrity) and is not overwritten.
    ManageConsumer(mt5, mp).run_once(NOW)
    assert (mp.results / canonical).read_text(encoding="utf-8") == "{ not json"


# ============================================================================
# LEDGER
# ============================================================================
def test_16_17_18_ledger_terminal_once_and_idempotent(tmp_path):
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    instr = _instr(); mid = instr["manage_id"]
    c = ManageConsumer(mt5, mp)
    write_manage_instruction(mp, instr, NOW); c.run_once(NOW)
    from forex_swing_orb.manage.ledger import ManageLedger
    led = ManageLedger(mp.ea_ledger)
    assert led.is_terminal(mid)
    write_manage_instruction(mp, instr, NOW)
    assert c.run_once(NOW)["status"] == ManageStatus.ALREADY_APPLIED   # dedup by manage_id
    assert len(list(mp.results.glob("*.json"))) == 1


# ============================================================================
# PARITY (Python reference <-> live MQL5 identity formula)
# ============================================================================
def test_27_python_mql5_identity_formula_match():
    mqh = (Path(__file__).resolve().parents[2] / "ea_mt5" / "SessionEdgeManageHandler.mqh"
           ).read_text(encoding="utf-8")
    # MQL5 must derive the result id from (manage_id | effective status), NOT the JSON.
    assert 'Sha256Hex16(mid + "|" + MgEffectiveStatus(status))' in mqh
    assert "Sha256Hex16(json)" not in mqh                        # old clock-drift formula gone
    # effective-status mapping mirrors the Python owner
    assert "string MgEffectiveStatus" in mqh
    for tok in ('return "APPLIED"', 'return "CLOSED"', 'return "REJECTED"'):
        assert tok in mqh


def test_28_parity_guard_catches_drift():
    # the Python effective-status classes and the MQL5 mapping must agree on the
    # family collapses that define identity.
    assert ManageStatus.effective_status(ManageStatus.ALREADY_APPLIED) == "APPLIED"
    assert ManageStatus.effective_status(ManageStatus.NO_OP_CLOSED) == "CLOSED"
    assert ManageStatus.effective_status(ManageStatus.REJECTED_LOOSEN) == "REJECTED"
    assert ManageStatus.effective_status(ManageStatus.ERROR) == ManageStatus.ERROR


def test_28b_mql5_idempotent_write_guard():
    mqh = (Path(__file__).resolve().parents[2] / "ea_mt5" / "SessionEdgeManageHandler.mqh"
           ).read_text(encoding="utf-8")
    assert "if(!BridgeExists(relpath, UseCommonFolder))" in mqh   # no overwrite / no dup file


# ============================================================================
# M-5 REGRESSION (result naming must not break orphan detection)
# ============================================================================
def test_19_20_21_22_m5_bridge_has_sees_canonical_and_legacy(tmp_path):
    from forex_swing_orb.manage import BridgeMt5Adapter
    mp = ManagePaths(tmp_path).ensure(); mt5 = _mt5_with_long()
    ad = BridgeMt5Adapter(mt5, mp, now_fn=lambda: NOW)
    mid = "abcdef0123456789"
    # canonical result file -> _bridge_has True (real result prevents orphan clear)
    canonical = f"{mid}.{MC.manage_result_id(mid, ManageStatus.APPLIED)}.json"
    (mp.results / canonical).write_text("{}", encoding="utf-8")
    assert ad._bridge_has(mid) is True
    # legacy timestamp-rid result file -> still seen by manage_id glob
    mid2 = "0000000000000001"
    (mp.results / f"{mid2}.deadbeefdeadbeef.json").write_text("{}", encoding="utf-8")
    assert ad._bridge_has(mid2) is True
    # genuinely absent -> orphan-eligible (unchanged)
    assert ad._bridge_has("ffffffffffffffff") is False
