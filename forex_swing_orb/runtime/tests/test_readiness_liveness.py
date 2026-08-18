"""TRUE READINESS / BRIDGE LIVENESS / OPERATOR VISIBILITY — test matrix.

Covers the two new canonical owners (runtime.ea_liveness, runtime.operator_status)
and the false-green removals wired into the producer dashboard and manager service.
Every timestamp is injected; nothing here touches MT5, the network, or a real EA.

The adversarial block at the end proves the hardening invariants (spec §T):
  * BRIDGE end-to-end is NOT READY on a Python-only probe (needs a fresh EA beat).
  * PRODUCER is NOT READY while any hard gate blocked the last cycle.
  * MANAGER state is NOT hard-coded READY.
  * SYSTEM is NOT READY without fresh EA liveness.
  * The EA heartbeat authorizes NOTHING (ea_liveness places/claims/writes nothing).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize                      # noqa: E402
from forex_swing_orb.runtime import ea_liveness as EL             # noqa: E402
from forex_swing_orb.runtime import operator_status as OS         # noqa: E402
from forex_swing_orb.producer.contract import CycleOutcome        # noqa: E402

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
BRIDGE_NAME = "session_edge_bridge"


def _write_status(root, **over):
    rec = {
        "artifact": EL.EA_STATUS_ARTIFACT,
        "schema_version": EL.EA_STATUS_SCHEMA,
        "ea_id": "SessionEdgeExecutionEA",
        "timestamp": serialize.iso_utc(NOW),
        "bridge_root": BRIDGE_NAME,
        "use_common_folder": False,
        "poll_seconds": 5,
        "data_path": None,
        "account_login": 123,
        "polling_active": True,
    }
    rec.update(over)
    p = EL.status_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(serialize.canonical_json(rec), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# ea_liveness (1–16)
# --------------------------------------------------------------------------- #
def test_01_missing_when_no_file(tmp_path):
    r = EL.read_ea_status(tmp_path, NOW)
    assert r.state == EL.MISSING and not r.ok


def test_02_python_never_creates_the_file(tmp_path):
    EL.read_ea_status(tmp_path, NOW)
    # A MISSING read must NOT fabricate the heartbeat (no false green by side effect).
    assert not EL.status_path(tmp_path).exists()


def test_03_malformed_when_unparseable(tmp_path):
    p = EL.status_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert EL.read_ea_status(tmp_path, NOW).state == EL.MALFORMED


def test_04_unknown_schema_wrong_artifact(tmp_path):
    _write_status(tmp_path, artifact="something_else")
    assert EL.read_ea_status(tmp_path, NOW).state == EL.UNKNOWN_SCHEMA


def test_05_unknown_schema_wrong_version(tmp_path):
    _write_status(tmp_path, schema_version=999)
    assert EL.read_ea_status(tmp_path, NOW).state == EL.UNKNOWN_SCHEMA


def test_06_malformed_missing_timestamp(tmp_path):
    _write_status(tmp_path, timestamp=None)
    assert EL.read_ea_status(tmp_path, NOW).state == EL.MALFORMED


def test_07_wrong_bridge_name_mismatch(tmp_path):
    _write_status(tmp_path, bridge_root="other_bridge")
    r = EL.read_ea_status(tmp_path, NOW)
    assert r.state == EL.WRONG_BRIDGE


def test_08_wrong_bridge_use_common_mismatch(tmp_path):
    _write_status(tmp_path, use_common_folder=True)
    r = EL.read_ea_status(tmp_path, NOW, expected_use_common=False)
    assert r.state == EL.WRONG_BRIDGE


def test_09_wrong_bridge_data_path_implies_other_abspath(tmp_path):
    _write_status(tmp_path, data_path="/some/other/terminal")
    r = EL.read_ea_status(
        tmp_path, NOW,
        expected_bridge_abspath="/the/selected/terminal/MQL5/Files/" + BRIDGE_NAME)
    assert r.state == EL.WRONG_BRIDGE


def test_10_stale_when_polling_inactive(tmp_path):
    _write_status(tmp_path, polling_active=False)
    assert EL.read_ea_status(tmp_path, NOW).state == EL.STALE


def test_11_stale_when_too_old(tmp_path):
    old = serialize.iso_utc(NOW - timedelta(seconds=120))
    _write_status(tmp_path, timestamp=old, poll_seconds=5)   # limit=20s
    assert EL.read_ea_status(tmp_path, NOW).state == EL.STALE


def test_12_stale_when_far_future(tmp_path):
    fut = serialize.iso_utc(NOW + timedelta(seconds=120))
    _write_status(tmp_path, timestamp=fut, poll_seconds=5)
    assert EL.read_ea_status(tmp_path, NOW).state == EL.STALE


def test_13_pass_when_fresh_same_bridge(tmp_path):
    _write_status(tmp_path)
    r = EL.read_ea_status(tmp_path, NOW)
    assert r.state == EL.PASS and r.ok
    assert r.data.get("ea_id") == "SessionEdgeExecutionEA"


def test_14_pass_tolerates_small_jitter(tmp_path):
    _write_status(tmp_path, timestamp=serialize.iso_utc(NOW - timedelta(seconds=8)))
    assert EL.read_ea_status(tmp_path, NOW).ok


def test_15_pass_with_matching_data_path_abspath(tmp_path):
    dp = "/T/MetaTrader5"
    _write_status(tmp_path, data_path=dp)
    abspath = str(Path(dp) / "MQL5" / "Files" / BRIDGE_NAME)
    assert EL.read_ea_status(tmp_path, NOW, expected_bridge_abspath=abspath).ok


def test_16_freshness_limit_formula():
    assert EL.freshness_limit(5) == 20.0            # 5*4
    assert EL.freshness_limit(1) == 15.0            # floor
    assert EL.freshness_limit(0) == 20.0            # 0 -> default 5 -> 20
    assert EL.freshness_limit("bad") == 20.0        # non-numeric -> default
    assert EL.freshness_limit(30) == 120.0          # scales


# --------------------------------------------------------------------------- #
# operator_status: producer (17–25)
# --------------------------------------------------------------------------- #
def test_17_producer_stopped_when_not_running():
    assert OS.producer_state(False, None)["state"] == OS.PRODUCER_STOPPED


def test_18_producer_running_no_cycle():
    assert OS.producer_state(True, None)["state"] == OS.PRODUCER_RUNNING


@pytest.mark.parametrize("outcome", sorted(OS._BLOCKED_OUTCOMES))
def test_19_producer_blocked_outcomes(outcome):
    r = OS.producer_state(True, {"outcome": outcome, "reason_codes": ["R_X"]})
    assert r["state"] == OS.PRODUCER_BLOCKED


@pytest.mark.parametrize("outcome", sorted(OS._WAITING_OUTCOMES))
def test_20_producer_waiting_outcomes(outcome):
    assert OS.producer_state(True, {"outcome": outcome})["state"] == OS.PRODUCER_WAITING


def test_21_producer_ready_on_instruction_written():
    r = OS.producer_state(True, {"outcome": "INSTRUCTION_WRITTEN"})
    assert r["state"] == OS.PRODUCER_READY


def test_22_producer_error_on_unit_error():
    assert OS.producer_state(True, {"outcome": "UNIT_ERROR"})["state"] == OS.PRODUCER_ERROR


def test_23_producer_unknown_outcome_fails_visible():
    assert OS.producer_state(True, {"outcome": "WAT"})["state"] == OS.PRODUCER_BLOCKED


def test_24_producer_accepts_cycleresult_object():
    from forex_swing_orb.producer.contract import CycleResult
    cr = CycleResult(cycle_id="x", symbol="EURUSD.FX", bar_ts="-",
                     outcome="NO_NEW_BAR", reason_codes=("R_NO_NEW_BAR",))
    assert OS.producer_state(True, cr)["state"] == OS.PRODUCER_WAITING


def test_25_known_outcomes_parity_with_contract():
    # operator_status must classify every real CycleOutcome (+ UNIT_ERROR). If this
    # fails, a new outcome was added without categorizing it here.
    contract_outcomes = set(CycleOutcome.ALL) | {"UNIT_ERROR"}
    assert OS.KNOWN_OUTCOMES == contract_outcomes


# --------------------------------------------------------------------------- #
# operator_status: manager (26–31)
# --------------------------------------------------------------------------- #
def test_26_manager_stopped():
    assert OS.manager_state(False, {})["state"] == OS.MANAGER_STOPPED


def test_27_manager_error_on_last_error():
    assert OS.manager_state(True, {"last_error": "boom",
                                   "terminal_connected": True})["state"] == OS.MANAGER_ERROR


def test_28_manager_disconnected():
    assert OS.manager_state(True, {"terminal_connected": False})["state"] == OS.MANAGER_DISCONNECTED


def test_29_manager_reconciliation_required():
    f = {"terminal_connected": True, "unresolved_reconciliation_count": 2}
    assert OS.manager_state(True, f)["state"] == OS.MANAGER_RECONCILIATION_REQUIRED


def test_30_manager_managing():
    f = {"terminal_connected": True, "tracked_tickets": 1}
    assert OS.manager_state(True, f)["state"] == OS.MANAGER_MANAGING


def test_31_manager_idle():
    assert OS.manager_state(True, {"terminal_connected": True})["state"] == OS.MANAGER_IDLE


# --------------------------------------------------------------------------- #
# bridge end-to-end + system (adversarial, 32–40)
# --------------------------------------------------------------------------- #
def test_32_bridge_ready_needs_fs_and_ea_pass():
    r = OS.bridge_end_to_end(True, EL.PASS)
    assert r["ready"] and r["state"] == OS.BRIDGE_END_TO_END_READY


def test_33_bridge_not_ready_python_only():
    # Filesystem PASS but EA MISSING must NOT read as end-to-end ready (T).
    r = OS.bridge_end_to_end(True, EL.MISSING)
    assert not r["ready"]
    assert any("EA liveness" in b for b in r["blockers"])


def test_34_bridge_not_ready_when_fs_fails():
    r = OS.bridge_end_to_end(False, EL.PASS)
    assert not r["ready"]
    assert any("filesystem" in b for b in r["blockers"])


def _e2e(state):
    return {"state": state, "ready": state == OS.BRIDGE_END_TO_END_READY,
            "blockers": () if state == OS.BRIDGE_END_TO_END_READY
            else ("EA liveness is MISSING (no fresh same-bridge EA heartbeat)",)}


def test_35_system_ready_when_all_good():
    r = OS.system_readiness(
        bridge_e2e=_e2e(OS.BRIDGE_END_TO_END_READY),
        producer={"state": OS.PRODUCER_WAITING, "detail": "waiting"},
        manager={"state": OS.MANAGER_IDLE, "detail": "idle"},
        anchor_available=True)
    assert r["ready"] and r["state"] == OS.SYSTEM_READY


def test_36_system_not_ready_without_fresh_ea():
    # Producer waiting + manager idle, but no EA beat -> SYSTEM must be NOT READY.
    r = OS.system_readiness(
        bridge_e2e=_e2e(OS.BRIDGE_END_TO_END_NOT_READY),
        producer={"state": OS.PRODUCER_WAITING, "detail": "waiting"},
        manager={"state": OS.MANAGER_IDLE, "detail": "idle"})
    assert not r["ready"]
    assert any("EA liveness" in b for b in r["blockers"])


def test_37_system_not_ready_when_producer_blocked():
    r = OS.system_readiness(
        bridge_e2e=_e2e(OS.BRIDGE_END_TO_END_READY),
        producer={"state": OS.PRODUCER_BLOCKED, "detail": "KILL_SWITCH"},
        manager={"state": OS.MANAGER_IDLE, "detail": "idle"})
    assert not r["ready"]
    assert any("producer" in b for b in r["blockers"])


def test_38_system_not_ready_when_manager_disconnected():
    r = OS.system_readiness(
        bridge_e2e=_e2e(OS.BRIDGE_END_TO_END_READY),
        producer={"state": OS.PRODUCER_WAITING, "detail": "waiting"},
        manager={"state": OS.MANAGER_DISCONNECTED, "detail": "no terminal"})
    assert not r["ready"]
    assert any("manager" in b for b in r["blockers"])


def test_39_system_not_ready_when_anchor_unavailable():
    r = OS.system_readiness(
        bridge_e2e=_e2e(OS.BRIDGE_END_TO_END_READY),
        producer={"state": OS.PRODUCER_WAITING, "detail": "waiting"},
        manager={"state": OS.MANAGER_IDLE, "detail": "idle"},
        anchor_available=False)
    assert not r["ready"]
    assert any("anchor" in b for b in r["blockers"])


def test_40_anchor_none_is_not_a_blocker_on_its_own():
    r = OS.system_readiness(
        bridge_e2e=_e2e(OS.BRIDGE_END_TO_END_READY),
        producer={"state": OS.PRODUCER_WAITING, "detail": "waiting"},
        manager={"state": OS.MANAGER_IDLE, "detail": "idle"},
        anchor_available=None)
    assert r["ready"]


# --------------------------------------------------------------------------- #
# wiring: no hard-coded READY leaks (41–43)
# --------------------------------------------------------------------------- #
def test_41_manager_service_has_no_hardcoded_ready():
    src = (REPO_ROOT / "forex_swing_orb" / "manage" / "service.py").read_text()
    assert '"service_state": "READY"' not in src
    assert "operator_status.manager_state(" in src


def test_42_dashboard_no_blanket_ready():
    src = (REPO_ROOT / "forex_swing_orb" / "producer" / "dashboard.py").read_text()
    assert '"READY" if demo_verified else "REFUSED"' not in src
    assert "operator_status.producer_state(" in src


def test_43_ea_liveness_never_writes():
    # The liveness owner must not contain any write/create call (read-only proof).
    src = (REPO_ROOT / "forex_swing_orb" / "runtime" / "ea_liveness.py").read_text()
    for banned in ("write_text(", "open(", "mkdir(", "touch("):
        assert banned not in src
