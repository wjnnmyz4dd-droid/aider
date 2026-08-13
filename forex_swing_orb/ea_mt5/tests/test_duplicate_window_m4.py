"""PR-3H / M4 — duplicate-order / execution-identity window (closure proof).

M4 is already covered by the exactly-once machinery closed in earlier PRs: the
bridge atomic claim + SeenResolver dedup (one terminal per signal_id), the
point-of-execution position_by_comment adopt guard (M1), bounded truth-checked
retry (M1), periodic/restart broker-truth reconciliation that never resends (G-1),
and claimed-file capacity reservation counted once (PR-4A.1/H5). These end-to-end
tests PROVE the M4 property invariants at HEAD; NO production change is made for M4.
"""

from __future__ import annotations

import tempfile

from forex_swing_orb.bridge.contract import ResultState, ReasonCode
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import instruction_name
from forex_swing_orb.producer.bridge_health import observe_entry_bridge
from forex_swing_orb.validation import harness as H

NOW = H.NOW


def _pos(mt5, sid, ticket=90):
    mt5.positions[ticket] = mock_mt5.Position(
        ticket=ticket, symbol="EURUSD", type=mock_mt5.ORDER_TYPE_BUY, volume=0.10,
        price_open=1.10000, sl=1.09800, tp=1.10400, comment=sid)


def _sends(mt5):
    return len(mt5.order_log)


# --------------------------------------------------------------------------- #
# property A: periodic reconciliation never increases the send count
# --------------------------------------------------------------------------- #
def test_A_periodic_reconcile_never_sends():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_TIMEOUT)          # ambiguous -> HELD
    rec = H.make_instruction(); H.produce(paths, rec); H.drain(ec)
    before = _sends(mt5)
    for _ in range(5):
        ec.reconcile_held(NOW)
    assert _sends(mt5) == before


# --------------------------------------------------------------------------- #
# property B: broker-positive truth prevents resend
# --------------------------------------------------------------------------- #
def test_B_broker_truth_prevents_resend():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_CONNECTION)       # ambiguous -> HELD
    rec = H.make_instruction(); H.produce(paths, rec); H.drain(ec)
    before = _sends(mt5)
    _pos(mt5, rec["signal_id"])                         # broker actually holds it
    ec.reconcile_held(NOW)
    assert _sends(mt5) == before                        # finalized from truth, never resent
    assert (paths.archive_accepted / instruction_name(rec["signal_id"])).exists()


# --------------------------------------------------------------------------- #
# property C: acknowledged unknown truth stays capacity-reserved
# --------------------------------------------------------------------------- #
def test_C_unknown_truth_reserves_capacity():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_TIMEOUT)
    rec = H.make_instruction(); H.produce(paths, rec); H.drain(ec)
    ec.reconcile_held(NOW)
    obs = observe_entry_bridge(paths, NOW)
    assert obs.outstanding_count == 1 and obs.missing_ack_count == 0


# --------------------------------------------------------------------------- #
# property D: duplicate bridge artifacts do not multiply execution
# --------------------------------------------------------------------------- #
def test_D_duplicate_pending_counts_once():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    rec = H.make_instruction()
    H.produce(paths, rec)
    first = H.drain(ec)[0]
    assert first["status"] == ResultState.EXECUTED
    H.produce(paths, rec)                               # re-deliver SAME signal_id
    second = H.drain(ec)[0]
    assert second["status"] == ResultState.DUPLICATE
    assert _sends(mt5) == 1                             # never a second order
    assert len([p for p in mt5.positions.values() if p.comment == rec["signal_id"]]) == 1


def test_D_duplicate_pending_and_claimed_observed_once():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    rec = H.make_instruction()
    sid = rec["signal_id"]
    from forex_swing_orb.bridge import serialize
    from forex_swing_orb.bridge.atomic import atomic_write_text
    body = serialize.dumps(serialize.with_integrity_digest(dict(rec)))
    atomic_write_text(paths.pending / instruction_name(sid), body)
    atomic_write_text(paths.claimed / instruction_name(sid), body)   # same sid in both
    obs = observe_entry_bridge(paths, NOW)
    assert obs.outstanding_count == 1                  # counted once (claimed wins)


# --------------------------------------------------------------------------- #
# property E: restart cannot turn ambiguous acknowledged work into a fresh send
# --------------------------------------------------------------------------- #
def test_E_restart_no_fresh_send():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_CONNECTION)
    rec = H.make_instruction(); H.produce(paths, rec); H.drain(ec)
    before = _sends(mt5)
    ec2, _, _ = H.reopen(paths, mt5)                    # simulate restart
    ec2.recover(NOW)
    assert _sends(mt5) == before                        # ack present, no pos -> no resend


def test_E_restart_with_broker_pos_finalizes_no_send():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_TIMEOUT)
    rec = H.make_instruction(); H.produce(paths, rec); H.drain(ec)
    before = _sends(mt5)
    _pos(mt5, rec["signal_id"])
    ec2, _, _ = H.reopen(paths, mt5)
    summary = ec2.recover(NOW)
    assert summary["recovered_from_broker"] == 1 and _sends(mt5) == before


# --------------------------------------------------------------------------- #
# property F: a terminalized signal cannot become executable again
# --------------------------------------------------------------------------- #
def test_F_terminalized_cannot_reopen():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    rec = H.make_instruction()
    H.produce(paths, rec); H.drain(ec)                 # EXECUTED, archived accepted
    before = _sends(mt5)
    H.produce(paths, rec)                               # re-deliver same signal_id
    r = H.drain(ec)[0]
    assert r["status"] == ResultState.DUPLICATE
    assert _sends(mt5) == before                        # terminal signal never re-executes


def test_F_rejected_terminal_cannot_reopen():
    ec, paths, l, a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_NO_MONEY)         # terminal reject
    rec = H.make_instruction()
    H.produce(paths, rec)
    assert H.drain(ec)[0]["status"] == ResultState.EXECUTION_FAILED
    before = _sends(mt5)
    H.produce(paths, rec)
    r = H.drain(ec)[0]
    assert r["status"] == ResultState.DUPLICATE and _sends(mt5) == before
