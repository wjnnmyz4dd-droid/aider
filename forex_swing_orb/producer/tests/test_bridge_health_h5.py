"""PR-3C (H5) — bridge liveness + acknowledgement health.

bridge_healthy and missing_ack_count are derived from ONE read-only entry-bridge
observation (no hardcoded True/0). ACK = the atomic claim (pending->claimed); the
ACK window is the instruction's own expiration_timestamp. Fresh pending latency is
never a failure; stale unacknowledged pending BLOCKS via ACK_MISSING; unreadable/
corrupt/future bridge state fails closed via BRIDGE_UNHEALTHY. Deterministic; no MT5.
"""

from __future__ import annotations

import pathlib
import shutil
from datetime import datetime, timedelta, timezone

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.producer.bridge_health import observe_entry_bridge
from forex_swing_orb.producer.contract import CycleOutcome
from forex_swing_orb.compliance.contract import ReasonCode, ComplianceConfig, FtmoProfile
from forex_swing_orb.compliance import gates as cgates
from conftest import NOW, make_runner  # noqa: F401  (make_runner is a fixture)

UTC = timezone.utc
GEN = NOW - timedelta(minutes=20)                 # instruction created 20 min ago
EXP_FRESH = NOW + timedelta(minutes=20)           # still valid -> fresh
EXP_STALE = NOW - timedelta(minutes=5)            # already past validity -> stale


def _paths(tmp_path):
    return BridgePaths(tmp_path / "bridge").ensure()


def _write(paths, sid, *, symbol="EURUSD.FX", gen=GEN, exp=EXP_FRESH, where="pending",
           body=None):
    d = {"pending": paths.pending, "claimed": paths.claimed}[where]
    if body is None:
        body = serialize.canonical_json({
            "signal_id": sid, "symbol": symbol, "risk_fraction": 0.0025,  # H-1: real intent risk
            "generated_timestamp": serialize.iso_utc(gen),
            "expiration_timestamp": serialize.iso_utc(exp)})
    (d / (sid + ".json")).write_text(body, encoding="utf-8")


SID_A = "aaaa0000aaaa0000"
SID_B = "bbbb1111bbbb1111"


# --------------------------------------------------------------------------- #
# unit: observe_entry_bridge (§29.1-4, §30 invariants)
# --------------------------------------------------------------------------- #
def test_no_outstanding_is_healthy(tmp_path):
    obs = observe_entry_bridge(_paths(tmp_path), NOW)
    assert obs.healthy and obs.missing_ack_count == 0 and obs.outstanding_count == 0


def test_fresh_pending_is_healthy_not_missing(tmp_path):
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy and obs.missing_ack_count == 0
    assert obs.outstanding_count == 1 and obs.outstanding_symbols == ("EURUSD.FX",)


def test_stale_pending_counts_missing_ack(tmp_path):
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_STALE)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy                                  # bridge infra fine; consumer not acking
    assert obs.missing_ack_count == 1 and SID_A in obs.stale_signal_ids
    assert obs.outstanding_count == 1                   # still reserves capacity


def test_two_stale_pending(tmp_path):
    p = _paths(tmp_path)
    _write(p, SID_A, exp=EXP_STALE); _write(p, SID_B, symbol="GBPUSD.FX", exp=EXP_STALE)
    obs = observe_entry_bridge(p, NOW)
    assert obs.missing_ack_count == 2


def test_claimed_is_acknowledged_not_missing(tmp_path):
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_STALE, where="claimed")
    obs = observe_entry_bridge(p, NOW)
    assert obs.missing_ack_count == 0                   # claim = acknowledgement
    assert obs.outstanding_count == 1                   # still capacity-reserved


def test_terminal_archived_not_counted(tmp_path):
    # a terminal signal has been MOVED to archive -> not in pending/claimed
    p = _paths(tmp_path)
    (p.archive_accepted / (SID_A + ".json")).write_text("{}", encoding="utf-8")
    obs = observe_entry_bridge(p, NOW)
    assert obs.outstanding_count == 0 and obs.missing_ack_count == 0 and obs.healthy


def test_duplicate_pending_and_claimed_counted_once(tmp_path):
    p = _paths(tmp_path)
    _write(p, SID_A, exp=EXP_STALE, where="pending")
    _write(p, SID_A, exp=EXP_STALE, where="claimed")   # same signal in both (claimed wins)
    obs = observe_entry_bridge(p, NOW)
    assert obs.outstanding_count == 1                   # one signal, one state
    assert obs.missing_ack_count == 0                  # claimed precedence -> acknowledged


def test_missing_pending_dir_fails_closed(tmp_path):
    p = _paths(tmp_path); shutil.rmtree(p.pending)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False and obs.missing_ack_count >= 1


def test_corrupt_instruction_fails_closed(tmp_path):
    p = _paths(tmp_path); _write(p, SID_A, body="{ not json")
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False


def test_future_instruction_fails_closed(tmp_path):
    p = _paths(tmp_path)
    _write(p, SID_A, gen=NOW + timedelta(minutes=10), exp=NOW + timedelta(minutes=40))
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False                          # future creation -> clock anomaly


def test_naive_now_fails_closed(tmp_path):
    obs = observe_entry_bridge(_paths(tmp_path), datetime(2026, 1, 1, 0, 0))
    assert obs.healthy is False


def test_bad_expiration_fails_closed(tmp_path):
    p = _paths(tmp_path)
    _write(p, SID_A, body=serialize.canonical_json(
        {"signal_id": SID_A, "symbol": "EURUSD.FX",
         "generated_timestamp": serialize.iso_utc(GEN)}))   # no expiration
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False


# --------------------------------------------------------------------------- #
# ACK-window boundary (§29.27-29, property B)
# --------------------------------------------------------------------------- #
def test_ack_window_boundary(tmp_path):
    p = _paths(tmp_path)
    exp = NOW
    _write(p, SID_A, gen=NOW - timedelta(minutes=30), exp=exp)
    just_before = observe_entry_bridge(p, exp - timedelta(seconds=1))
    at_boundary = observe_entry_bridge(p, exp)
    after = observe_entry_bridge(p, exp + timedelta(seconds=1))
    assert just_before.missing_ack_count == 0           # within window -> not missing
    assert at_boundary.missing_ack_count == 1           # now >= expiration -> missing
    assert after.missing_ack_count == 1


# --------------------------------------------------------------------------- #
# restart / property C: age derives from persisted instruction, not memory
# --------------------------------------------------------------------------- #
def test_restart_does_not_reset_ack_age(tmp_path):
    p = _paths(tmp_path); _write(p, SID_A, gen=GEN, exp=EXP_STALE)
    later = NOW + timedelta(hours=2)
    o1 = observe_entry_bridge(p, NOW)
    o2 = observe_entry_bridge(p, later)                  # a fresh "process" re-reads disk
    assert o1.missing_ack_count == 1 and o2.missing_ack_count == 1
    assert o2.oldest_unacked_age_sec > o1.oldest_unacked_age_sec   # age only grows


def test_adding_stale_never_decreases_missing_ack(tmp_path):   # property E
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_STALE)
    before = observe_entry_bridge(p, NOW).missing_ack_count
    _write(p, SID_B, symbol="GBPUSD.FX", exp=EXP_STALE)
    after = observe_entry_bridge(p, NOW).missing_ack_count
    assert after >= before and after == before + 1


# --------------------------------------------------------------------------- #
# compliance authority: facts -> gate (§20)
# --------------------------------------------------------------------------- #
def _bh(**over):
    base = {"terminal_connected": True, "bridge_healthy": True, "spread_points": 1.0,
            "max_spread_points": 20.0, "recent_slippage_points": 0.0,
            "max_slippage_points": 15.0, "missing_ack_count": 0, "quote_age_sec": 1.0,
            "max_quote_age_sec": 30.0}
    base.update(over)
    return base


def test_gate_blocks_on_unhealthy_bridge():
    v = cgates.gate_broker_health(_bh(bridge_healthy=False), NOW)
    assert not v.passed and ReasonCode.BRIDGE_UNHEALTHY in v.reason_codes


def test_gate_blocks_on_missing_ack():
    v = cgates.gate_broker_health(_bh(missing_ack_count=2), NOW)
    assert not v.passed and ReasonCode.ACK_MISSING in v.reason_codes


def test_gate_passes_when_healthy_and_acked():
    assert cgates.gate_broker_health(_bh(), NOW).passed


# --------------------------------------------------------------------------- #
# end-to-end through the runner: stale/unhealthy bridge blocks new entries
# --------------------------------------------------------------------------- #
def _pending_files(paths):
    return sorted(p.name for p in paths.pending.glob("*.json"))


def test_stale_pending_blocks_new_entry_via_runner(make_runner):
    runner, d = make_runner()
    # pre-seed a STALE unacknowledged entry from another (session/symbol)
    _write(d["paths"], "cccc2222cccc2222", symbol="USDJPY.FX", gen=GEN, exp=EXP_STALE)
    before = _pending_files(d["paths"])
    res = runner.run_cycle(NOW)
    r = res[0]
    assert r.outcome == CycleOutcome.COMPLIANCE_REJECT
    assert ReasonCode.ACK_MISSING in r.reason_codes
    assert _pending_files(d["paths"]) == before          # producer wrote NOTHING new


def test_unreadable_bridge_blocks_new_entry_via_runner(make_runner):
    runner, d = make_runner()
    shutil.rmtree(d["paths"].pending)                    # bridge infra failure
    res = runner.run_cycle(NOW)
    assert res[0].outcome == CycleOutcome.COMPLIANCE_REJECT
    assert ReasonCode.BRIDGE_UNHEALTHY in res[0].reason_codes


def test_fresh_pending_does_not_block(make_runner):
    # a fresh (within-window) pending entry does not trip ACK_MISSING: normal latency
    runner, d = make_runner()
    _write(d["paths"], "dddd3333dddd3333", symbol="USDJPY.FX", gen=NOW, exp=EXP_FRESH)
    res = runner.run_cycle(NOW)
    assert res[0].outcome == CycleOutcome.INSTRUCTION_WRITTEN   # EURUSD candidate still writes


# --------------------------------------------------------------------------- #
# account-global (§17/§18, property F): stale entry blocks ALL sessions/symbols
# --------------------------------------------------------------------------- #
def test_stale_ack_is_account_global(make_runner):
    # a stale TOKYO/USDJPY entry blocks a new EURUSD (default LONDON) entry:
    # switching symbol or session cannot bypass the account-global ACK block.
    runner, d = make_runner(symbols=("EURUSD.FX",))
    _write(d["paths"], "eeee4444eeee4444", symbol="USDJPY.FX", gen=GEN, exp=EXP_STALE)
    res = runner.run_cycle(NOW)
    assert res[0].outcome == CycleOutcome.COMPLIANCE_REJECT
    assert ReasonCode.ACK_MISSING in res[0].reason_codes


# --------------------------------------------------------------------------- #
# manager bridge traffic is NOT counted as entry ACK (§19)
# --------------------------------------------------------------------------- #
def test_manager_bridge_traffic_not_counted(tmp_path):
    from forex_swing_orb.manage.paths import ManagePaths
    p = _paths(tmp_path)
    mp = ManagePaths(tmp_path / "bridge").ensure()       # same root, separate namespace
    (mp.pending / ("ffff5555ffff5555.json")).write_text(
        serialize.canonical_json({"signal_id": "ffff5555ffff5555", "symbol": "EURUSD.FX",
                                  "generated_timestamp": serialize.iso_utc(GEN),
                                  "expiration_timestamp": serialize.iso_utc(EXP_STALE)}),
        encoding="utf-8")
    obs = observe_entry_bridge(p, NOW)
    assert obs.outstanding_count == 0 and obs.missing_ack_count == 0   # manage != entry


# --------------------------------------------------------------------------- #
# F-H5-1 — concurrent-claim TOCTOU: a file that vanishes mid-scan is reconciled
# against CURRENT authoritative bridge state (claimed/ + terminal) before any
# failure verdict. A normal consumer claim (pending->claimed FileMove) or a
# terminal archive move MUST NOT be misread as a bridge failure.
#
# The consumer's atomic claim / terminal move is modeled deterministically by an
# injected read hook that performs the real filesystem move BETWEEN directory
# enumeration and the observer's read of that file, then raises FileNotFoundError
# exactly as os-level read of a moved-away path would (§19 FileMove semantics).
# --------------------------------------------------------------------------- #
def _inject_move_on_read(monkeypatch, *, src, dst_dir, sid, delete=False):
    """Patch Path.read_text so the FIRST read of ``src``/<sid>.json performs the
    move ``src -> dst_dir`` (or delete) then raises FileNotFoundError, modeling a
    concurrent consumer claim/terminal move happening mid-scan. All other reads
    (including the observer's re-read of the moved-to location) behave normally."""
    orig = pathlib.Path.read_text
    fired = {"done": False}
    name = sid + ".json"

    def hooked(self, *a, **k):
        if not fired["done"] and self.name == name and self.parent == src:
            fired["done"] = True
            if delete:
                (src / name).unlink()
            else:
                shutil.move(str(src / name), str(dst_dir / name))
            raise FileNotFoundError(str(self))
        return orig(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", hooked)
    return fired


def test_pending_claimed_midscan_is_healthy_acknowledged(tmp_path, monkeypatch):
    # pending -> claimed (normal atomic FileMove) while the observer scans:
    # reconcile to claimed -> healthy, acknowledged, counted ONCE.
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH, where="pending")
    fired = _inject_move_on_read(monkeypatch, src=p.pending, dst_dir=p.claimed, sid=SID_A)
    obs = observe_entry_bridge(p, NOW)
    assert fired["done"]                                  # the concurrent claim really happened
    assert obs.healthy and obs.reason == ""
    assert obs.outstanding_count == 1                     # counted once, not zero and not two
    assert obs.missing_ack_count == 0                     # claim IS the acknowledgement
    assert obs.outstanding_symbols == ("EURUSD.FX",)


def test_stale_pending_claimed_midscan_not_missing_ack(tmp_path, monkeypatch):
    # even a PENDING that had missed its ACK window becomes acknowledged the instant
    # it is claimed mid-scan -> reconcile to claimed -> NOT missing-ack, healthy.
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_STALE, where="pending")
    _inject_move_on_read(monkeypatch, src=p.pending, dst_dir=p.claimed, sid=SID_A)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy and obs.missing_ack_count == 0 and obs.outstanding_count == 1


def test_pending_archived_midscan_released_healthy(tmp_path, monkeypatch):
    # pending -> archive/accepted (terminal) mid-scan: terminal evidence -> released,
    # not outstanding, healthy.
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH, where="pending")
    _inject_move_on_read(monkeypatch, src=p.pending, dst_dir=p.archive_accepted, sid=SID_A)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy and obs.outstanding_count == 0 and obs.missing_ack_count == 0


def test_pending_vanishes_no_evidence_fails_closed(tmp_path, monkeypatch):
    # pending disappears from EVERY authoritative state with no terminal evidence:
    # ambiguous bridge state -> FAIL CLOSED (never silently healthy).
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH, where="pending")
    _inject_move_on_read(monkeypatch, src=p.pending, dst_dir=None, sid=SID_A, delete=True)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False and obs.missing_ack_count >= 1
    assert SID_A in obs.reason


def test_claimed_archived_midscan_released_healthy(tmp_path, monkeypatch):
    # claimed -> archive/accepted (terminal) mid-scan: terminal evidence -> released.
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH, where="claimed")
    _inject_move_on_read(monkeypatch, src=p.claimed, dst_dir=p.archive_accepted, sid=SID_A)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy and obs.outstanding_count == 0 and obs.missing_ack_count == 0


def test_claimed_vanishes_no_terminal_fails_closed(tmp_path, monkeypatch):
    # claimed disappears with NO terminal evidence -> unexplained -> FAIL CLOSED.
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH, where="claimed")
    _inject_move_on_read(monkeypatch, src=p.claimed, dst_dir=None, sid=SID_A, delete=True)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False and obs.missing_ack_count >= 1


def test_permission_error_midscan_still_fails_closed(tmp_path, monkeypatch):
    # a NON-FileNotFound I/O error (e.g. permission) is NOT a benign disappearance:
    # it must stay fail-closed, never reconciled to healthy.
    p = _paths(tmp_path); _write(p, SID_A, exp=EXP_FRESH, where="pending")
    orig = pathlib.Path.read_text

    def hooked(self, *a, **k):
        if self.name == SID_A + ".json" and self.parent == p.pending:
            raise PermissionError("denied")
        return orig(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", hooked)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy is False and obs.missing_ack_count >= 1


def test_duplicate_pending_claimed_midscan_counted_once(tmp_path, monkeypatch):
    # a signal already present in claimed/ AND still listed in pending (it moved
    # after claimed enumeration): the pending read vanishes, reconcile finds it in
    # claimed -> still counted exactly once.
    p = _paths(tmp_path)
    _write(p, SID_A, exp=EXP_FRESH, where="claimed")     # already enumerated as claimed
    _write(p, SID_A, exp=EXP_FRESH, where="pending")     # stale duplicate listing
    # the pending read will "vanish" (already claimed); reconcile confirms claimed
    _inject_move_on_read(monkeypatch, src=p.pending, dst_dir=None, sid=SID_A, delete=True)
    obs = observe_entry_bridge(p, NOW)
    assert obs.healthy and obs.outstanding_count == 1 and obs.missing_ack_count == 0
