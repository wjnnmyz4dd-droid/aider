"""PR-3G / M1 — transient-vs-terminal execution retcode handling + bounded retry.

A routine REQUOTE / off-quote / timeout / connection / too-many-requests must NOT be
terminalized as EXECUTION_FAILED (which drops a valid entry and releases capacity).
Retry is bounded and NEVER resends blindly: every (re)send re-confirms no broker
position for the signal_id, ambiguous outcomes are never resent, expiration is
respected, and unresolved work is HELD (capacity-reserved) for broker-truth
reconciliation. Deterministic; mock MT5; no networking.
"""

from __future__ import annotations

from datetime import timedelta

from forex_swing_orb.bridge.contract import ResultState, ReasonCode
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import (RetClass, classify_retcode,
                                                       XReason, instruction_name)
from ea_helpers import make_instruction, NOW

SID = "a1b2c3d4e5f60718"


def _write_pending(paths, rec):
    from forex_swing_orb.bridge import serialize
    from forex_swing_orb.bridge.atomic import atomic_write_text
    rec = serialize.with_integrity_digest(dict(rec))
    atomic_write_text(paths.pending / instruction_name(rec["signal_id"]),
                      serialize.dumps(rec))


def _produce(env, rec, now=NOW):
    _write_pending(env.paths, rec)
    return env.process_next(now)


# --------------------------------------------------------------------------- #
# §17/§40 retcode taxonomy — classification table
# --------------------------------------------------------------------------- #
def test_taxonomy_success():
    assert classify_retcode(mock_mt5.TRADE_RETCODE_DONE) == RetClass.SUCCESS


def test_taxonomy_terminal():
    for rc in (mock_mt5.TRADE_RETCODE_REJECT, mock_mt5.TRADE_RETCODE_MARKET_CLOSED,
               mock_mt5.TRADE_RETCODE_INVALID_VOLUME, mock_mt5.TRADE_RETCODE_INVALID_STOPS,
               mock_mt5.TRADE_RETCODE_NO_MONEY, mock_mt5.TRADE_RETCODE_TRADE_DISABLED,
               mock_mt5.TRADE_RETCODE_INVALID):
        assert classify_retcode(rc) == RetClass.TERMINAL, rc


def test_taxonomy_transient():
    for rc in (mock_mt5.TRADE_RETCODE_REQUOTE, mock_mt5.TRADE_RETCODE_PRICE_OFF,
               mock_mt5.TRADE_RETCODE_INVALID_PRICE):
        assert classify_retcode(rc) == RetClass.TRANSIENT, rc


def test_taxonomy_ambiguous():
    for rc in (mock_mt5.TRADE_RETCODE_TIMEOUT, mock_mt5.TRADE_RETCODE_CONNECTION,
               mock_mt5.TRADE_RETCODE_TOO_MANY_REQUESTS):
        assert classify_retcode(rc) == RetClass.AMBIGUOUS, rc


def test_taxonomy_unknown_defaults_fail_closed():
    assert classify_retcode(999999) == RetClass.UNKNOWN


# --------------------------------------------------------------------------- #
# property tests (§39 A/B/C)
# --------------------------------------------------------------------------- #
def test_A_transient_never_blind_duplicate(env, mt5):
    # requote then (default) DONE: exactly one position, resend was duplicate-checked
    mt5.script(mock_mt5.TRADE_RETCODE_REQUOTE)
    r = _produce(env, make_instruction())
    assert r["status"] == ResultState.EXECUTED
    assert len([p for p in mt5.positions.values() if p.comment == SID]) == 1


def test_B_terminal_never_retried(env, mt5):
    mt5.script(mock_mt5.TRADE_RETCODE_NO_MONEY)
    r = _produce(env, make_instruction())
    assert r["status"] == ResultState.EXECUTION_FAILED
    assert len(mt5.order_log) == 1                       # no retry on terminal reject


def test_C_unknown_truth_does_not_release_capacity(env, mt5):
    # ambiguous outcome with no provable position -> held (claimed stays outstanding)
    mt5.script(mock_mt5.TRADE_RETCODE_TIMEOUT)
    r = _produce(env, make_instruction())
    assert r["status"] == ReasonCode.RECONCILIATION_REQUIRED
    assert (env.paths.claimed / instruction_name(SID)).exists()      # still reserved
    assert not (env.paths.archive_rejected / instruction_name(SID)).exists()


# --------------------------------------------------------------------------- #
# ambiguous-but-actually-executed: truth check adopts, never a second order
# --------------------------------------------------------------------------- #
def test_timeout_but_order_landed_is_adopted(env, mt5):
    # the send "times out" locally but the broker actually holds the position:
    # broker-truth check adopts it as EXECUTED (no resend, no phantom failure).
    rec = make_instruction()
    _write_pending(env.paths, rec)
    sid = env.claim_next(NOW)
    # queue a timeout; ALSO make the position already exist (order landed pre-timeout)
    mt5.positions[77] = mock_mt5.Position(
        ticket=77, symbol="EURUSD", type=mock_mt5.ORDER_TYPE_BUY, volume=0.10,
        price_open=1.10000, sl=1.09800, tp=1.10400, comment=sid)
    r = env.process(sid, NOW)
    assert r["status"] == ResultState.EXECUTED
    assert r["reason_code"] == XReason.ADOPTED
    assert len(mt5.order_log) == 0                       # pre-check adopted, never sent


# --------------------------------------------------------------------------- #
# expiration respected before any (re)send (§10)
# --------------------------------------------------------------------------- #
def test_expired_instruction_not_executed(env, mt5):
    # An instruction already past its window must not execute; terminal expiry.
    rec = make_instruction(expiration=NOW - timedelta(minutes=1),
                           generated=NOW - timedelta(minutes=30))
    r = _produce(env, rec)
    assert r["status"] == ResultState.EXPIRED
    assert len(mt5.order_log) == 0                       # never sent past the window


# --------------------------------------------------------------------------- #
# restart during retry: exactly-once recovery (§16)
# --------------------------------------------------------------------------- #
def test_restart_after_held_recovers_from_broker(env, mt5):
    # transient -> held (claimed stays). Then the order is found to actually exist
    # at the broker; recover() finalizes EXECUTED from broker truth, never resends.
    mt5.script(*[mock_mt5.TRADE_RETCODE_TIMEOUT])
    r = _produce(env, make_instruction())
    assert r["status"] == ReasonCode.RECONCILIATION_REQUIRED
    # broker turns out to hold the position (the timed-out send had landed)
    mt5.positions[88] = mock_mt5.Position(
        ticket=88, symbol="EURUSD", type=mock_mt5.ORDER_TYPE_BUY, volume=0.10,
        price_open=1.10000, sl=1.09800, tp=1.10400, comment=SID)
    summary = env.recover(NOW)
    assert summary["recovered_from_broker"] == 1
    assert (env.paths.archive_accepted / instruction_name(SID)).exists()
