"""Phase 3A - failure injection at every stage.

Every injected failure must: fail closed (no order, no torn artifact), produce a
deterministic audit trail, and recover correctly once the fault clears.
"""

from __future__ import annotations

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.contract import ResultState, ReasonCode
from forex_swing_orb.bridge.paths import instruction_name
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import XReason
from forex_swing_orb.validation import harness as H

NOW = H.NOW


def _audit_has(audit, action, reason=None):
    return any(a["action"] == action and (reason is None or a["reason_code"] == reason)
              for a in audit.read_all())


# -- TERMINAL broker rejections: fail closed + deterministic reason + audit ---
# (M1) Only genuine business rejections terminalize; transient/ambiguous outcomes
# are handled below and must NOT be terminalized as failures.
TERMINAL_CASES = [
    (mock_mt5.TRADE_RETCODE_REJECT, XReason.BROKER_REJECT),
    (mock_mt5.TRADE_RETCODE_MARKET_CLOSED, XReason.MARKET_CLOSED),
    (mock_mt5.TRADE_RETCODE_NO_MONEY, XReason.NO_MONEY),
    (mock_mt5.TRADE_RETCODE_INVALID_VOLUME, XReason.INVALID_VOLUME),
]


@pytest.mark.parametrize("retcode,reason", TERMINAL_CASES)
def test_broker_terminal_rejection_fails_closed(tmp_path, retcode, reason):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    mt5.script(retcode)
    rec = H.make_instruction()
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.EXECUTION_FAILED
    assert result["reason_code"] == reason
    assert result["execution_error"]["retcode"] == retcode
    assert mt5.position_by_comment(rec["signal_id"]) is None      # no open position
    assert len(mt5.order_log) == 1                                # terminal -> no retry
    assert _audit_has(audit, "process", reason)
    assert (paths.archive_rejected / instruction_name(rec["signal_id"])).exists()


# -- TRANSIENT: a routine requote/off-quote is retried (bounded) and succeeds ---
@pytest.mark.parametrize("retcode", [mock_mt5.TRADE_RETCODE_REQUOTE,
                                     mock_mt5.TRADE_RETCODE_PRICE_OFF])
def test_transient_failure_retried_then_executes(tmp_path, retcode):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    mt5.script(retcode)                              # one transient, then DONE
    rec = H.make_instruction()
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    assert result["status"] == ResultState.EXECUTED          # not dropped
    assert mt5.position_by_comment(rec["signal_id"]) is not None
    assert len(mt5.order_log) == 2                            # requote + resend


# -- AMBIGUOUS: too-many-requests is held (never resent, never terminalized) ---
def test_ambiguous_retcode_held_not_failed(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    mt5.script(mock_mt5.TRADE_RETCODE_TOO_MANY_REQUESTS)
    rec = H.make_instruction()
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    assert result["status"] == ReasonCode.RECONCILIATION_REQUIRED    # held, not failed
    assert mt5.position_by_comment(rec["signal_id"]) is None
    assert len(mt5.order_log) == 1                                    # not hammered
    # claimed instruction is HELD (capacity-reserved), not archived as rejected
    assert (paths.claimed / instruction_name(rec["signal_id"])).exists()
    assert not (paths.archive_rejected / instruction_name(rec["signal_id"])).exists()


def test_terminal_disconnected_held_not_failed(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    mt5.connected = False
    rec = H.make_instruction()
    H.produce(paths, rec)
    result = H.drain(ec)[0]
    # a disconnect is ambiguous (order may have reached the server) -> held, never
    # marked definitely-failed; the claimed instruction stays for reconciliation.
    assert result["status"] == ReasonCode.RECONCILIATION_REQUIRED
    assert mt5.position_by_comment(rec["signal_id"]) is None
    assert (paths.claimed / instruction_name(rec["signal_id"])).exists()
    # reconnect + a fresh signal executes normally (recovers)
    mt5.connected = True
    rec2 = H.make_instruction(i=2)
    H.produce(paths, rec2)
    assert H.drain(ec)[0]["status"] == ResultState.EXECUTED


# -- filesystem failures on write ------------------------------------------
def test_filesystem_permission_error_on_produce(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    with H.fail_permission_on_write():
        with pytest.raises((PermissionError, OSError)):
            H.produce(paths, rec)
    assert not (paths.pending / instruction_name(sid)).exists()   # fail closed
    # fault cleared -> works
    H.produce(paths, rec)
    assert H.drain(ec)[0]["status"] == ResultState.EXECUTED


def test_filesystem_full_on_produce(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    with H.fail_disk_full_on_write():
        with pytest.raises(OSError):
            H.produce(paths, rec)
    assert not (paths.pending / instruction_name(sid)).exists()
    H.produce(paths, rec)
    assert H.drain(ec)[0]["status"] == ResultState.EXECUTED


def test_partial_write_leaves_no_visible_artifact(tmp_path):
    """Power-loss during an atomic write: os.replace fails, so only a .tmp
    remains and it never becomes visible. Recovery cleans it."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    with H.fail_os_replace():
        with pytest.raises(OSError):
            H.produce(paths, rec)
    assert not (paths.pending / instruction_name(sid)).exists()   # never visible
    tmps = [p for p in paths.pending.iterdir() if p.name.endswith(".tmp")]
    assert tmps, "a torn temp file remains"
    ec.recover(NOW)                                              # cleans .tmp
    assert not [p for p in paths.pending.iterdir() if p.name.endswith(".tmp")]
    # after recovery a fresh produce/execute works
    H.produce(paths, rec)
    assert H.drain(ec)[0]["status"] == ResultState.EXECUTED


def test_write_failure_during_execution_no_order_leak(tmp_path):
    """If ack/result writes fail during processing, no order is placed and no
    terminal artifact is left; a later run executes exactly once."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW)
    with H.fail_permission_on_write():
        with pytest.raises((PermissionError, OSError)):
            ec.process(sid, NOW)
    assert mt5.position_by_comment(sid) is None                  # no order leaked
    assert not [p for p in paths.results.iterdir()]             # no terminal result
    # restart + recover -> safe single execution
    ec2, _, _ = H.reopen(paths, mt5)
    ec2.recover(NOW)
    assert len([o for o in mt5.order_log if o.get("comment") == sid]) == 1
    rid = serialize.result_id(sid, ResultState.EXECUTED)
    assert (paths.results / f"{sid}.{rid}.json").exists()


# -- corruption -------------------------------------------------------------
def test_bridge_corruption_of_claimed_file(tmp_path):
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW)
    (paths.claimed / instruction_name(sid)).write_text("corrupt{not json")
    result = ec.process(sid, NOW)
    assert result is None                                       # quarantined
    assert (paths.quarantine / instruction_name(sid)).exists()
    assert _audit_has(audit, "quarantine")
    assert mt5.position_by_comment(sid) is None


def test_conflicting_evidence_fails_closed(tmp_path):
    """Both accepted and rejected archive artifacts for one signal_id => the
    resolver refuses to guess and quarantines (fail closed)."""
    ec, paths, ledger, audit, mt5 = H.build(tmp_path)
    rec = H.make_instruction(); sid = rec["signal_id"]
    H.produce(paths, rec)
    ec.claim(sid, NOW)
    # plant contradictory terminal evidence
    (paths.archive_accepted / instruction_name(sid)).write_text("{}")
    (paths.archive_rejected / instruction_name(sid)).write_text("{}")
    result = ec.process(sid, NOW)
    assert result is None
    assert (paths.quarantine / instruction_name(sid)).exists()
    assert mt5.position_by_comment(sid) is None
