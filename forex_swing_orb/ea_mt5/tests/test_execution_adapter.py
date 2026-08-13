"""Behavioural tests for the Session Edge MT5 Execution Adapter (Phase 3).

These exercise the full execution protocol against a mock MT5 terminal:
claim -> validate -> ack -> order -> result -> recovery. They are the executable
acceptance criteria for the shipped MQL5 EA (which cannot be compiled/run here).
Deterministic and stdlib-only (pytest); no networking.
"""

from __future__ import annotations

from pathlib import Path

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.atomic import atomic_write_text
from forex_swing_orb.bridge.contract import ResultState
from forex_swing_orb.bridge.paths import ack_name, instruction_name, result_name
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.ea_mt5.execution_consumer import XReason, normalize_symbol

from ea_helpers import make_instruction, NOW


# -- helpers ----------------------------------------------------------------
def _write_pending(paths, record):
    rec = serialize.with_integrity_digest(record)
    atomic_write_text(paths.pending / instruction_name(rec["signal_id"]),
                      serialize.dumps(rec))
    return rec


def _read_result(paths, signal_id, status):
    rid = serialize.result_id(signal_id, status)
    p = paths.results / result_name(signal_id, rid)
    ok, text, _ = (p.exists(), p.read_text() if p.exists() else None, "")
    assert ok, f"missing result {p}"
    parsed, rec = serialize.loads(text)
    assert parsed
    return rec


def _produce(env, record, now=NOW):
    _write_pending(env.paths, record)
    return env.process_next(now)


# -- symbol normalization ---------------------------------------------------
def test_normalize_symbol_strips_fx_suffix():
    assert normalize_symbol("EURUSD.FX") == "EURUSD"
    assert normalize_symbol("EURUSD.FX", broker_suffix=".raw") == "EURUSD.raw"


def test_normalize_symbol_rejects_noncanonical():
    assert normalize_symbol("EURUSD") is None
    assert normalize_symbol("EUR.FX") is None
    assert normalize_symbol("eurusd.FX") is None
    assert normalize_symbol(None) is None


# -- successful BUY / SELL --------------------------------------------------
def test_successful_buy(env, mt5):
    rec = make_instruction(direction="LONG")
    result = _produce(env, rec)
    assert result["status"] == ResultState.EXECUTED
    assert result["reason_code"] == XReason.OK
    assert result["broker_order_id"] is not None
    assert result["filled_price"] == mt5.symbols["EURUSD"].ask   # BUY fills at ask
    assert result["filled_volume"] == env.default_volume
    # exactly one broker order, tagged with the signal_id
    assert len(mt5.order_log) == 1
    pos = mt5.position_by_comment(rec["signal_id"])
    assert pos is not None and pos.type == mock_mt5.ORDER_TYPE_BUY
    # terminal result archived to the accepted family
    assert (env.paths.archive_accepted / instruction_name(rec["signal_id"])).exists()


def test_successful_sell(env, mt5):
    rec = make_instruction(signal_id="b1b2c3d4e5f60718", direction="SHORT")
    result = _produce(env, rec)
    assert result["status"] == ResultState.EXECUTED
    pos = mt5.position_by_comment(rec["signal_id"])
    assert pos.type == mock_mt5.ORDER_TYPE_SELL
    assert result["filled_price"] == mt5.symbols["EURUSD"].bid   # SELL fills at bid


def test_direction_taken_verbatim_not_computed(env, mt5):
    """The adapter never decides direction: LONG->BUY, SHORT->SELL, nothing else."""
    _produce(env, make_instruction(signal_id="1111111111111111", direction="LONG"))
    _produce(env, make_instruction(signal_id="2222222222222222", direction="SHORT"))
    types = sorted(p.type for p in mt5.positions.values())
    assert types == [mock_mt5.ORDER_TYPE_BUY, mock_mt5.ORDER_TYPE_SELL]


# -- acknowledgement --------------------------------------------------------
def test_acknowledgement_written_before_result(env):
    rec = make_instruction()
    _produce(env, rec)
    ack_id = serialize.result_id(rec["signal_id"], "ACK")
    ack_path = env.paths.acks / ack_name(rec["signal_id"], ack_id)
    assert ack_path.exists()
    parsed, ack = serialize.loads(ack_path.read_text())
    assert parsed and ack["status"] == "ACK"
    assert ack["detail"]["ea_id"] == env.ea_id
    assert ack["detail"]["mt5_terminal_id"] == "MOCK-TERMINAL-1"
    assert ack["signal_id"] == rec["signal_id"]


# -- execution result writing ----------------------------------------------
def test_execution_result_fields(env, mt5):
    rec = make_instruction()
    result = _produce(env, rec)
    for field in ("signal_id", "result_id", "status", "reason_code",
                  "received_timestamp", "processed_timestamp", "stop_loss",
                  "take_profit", "broker_order_id", "requested_price",
                  "filled_price", "requested_volume", "filled_volume", "slippage"):
        assert field in result, field
    assert result["requested_price"] == rec["entry_price"]
    assert result["stop_loss"] == rec["stop_loss"]
    assert result["take_profit"] == rec["take_profit"]
    assert result["reason_detail"]["ticket"] == result["broker_order_id"]
    assert result["reason_detail"]["direction"] == "LONG"


# -- validation: expiry / digest / schema / strategy / completeness ---------
def test_expired_instruction_never_orders(env, mt5):
    from datetime import timedelta
    rec = make_instruction(expiration=NOW - timedelta(minutes=1))
    result = _produce(env, rec)
    assert result["status"] == ResultState.EXPIRED
    assert len(mt5.order_log) == 0
    # no ack: expiry is rejected before execution ownership
    ack_id = serialize.result_id(rec["signal_id"], "ACK")
    assert not (env.paths.acks / ack_name(rec["signal_id"], ack_id)).exists()


def test_digest_mismatch_rejected(env, mt5):
    rec = serialize.with_integrity_digest(make_instruction())
    rec["entry_price"] = 9.99999                       # tamper after digest
    atomic_write_text(env.paths.pending / instruction_name(rec["signal_id"]),
                      serialize.dumps(rec))
    result = env.process_next(NOW)
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_INTEGRITY"
    assert len(mt5.order_log) == 0


def test_schema_mismatch_rejected(env, mt5):
    result = _produce(env, make_instruction(schema_version=999))
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_SCHEMA"
    assert len(mt5.order_log) == 0


def test_strategy_version_mismatch_rejected(env, mt5):
    result = _produce(env, make_instruction(strategy_version="swing_orb.v9.9.9"))
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_STRATEGY"
    assert len(mt5.order_log) == 0


def test_incomplete_instruction_rejected(env, mt5):
    rec = make_instruction()
    del rec["take_profit"]
    rec = serialize.with_integrity_digest(rec)
    atomic_write_text(env.paths.pending / instruction_name(rec["signal_id"]),
                      serialize.dumps(rec))
    result = env.process_next(NOW)
    assert result["status"] == ResultState.REJECTED
    assert result["reason_code"] == "E_FIELDS"
    assert len(mt5.order_log) == 0


# -- broker-side input validation (broker, not strategy) --------------------
def test_unknown_broker_symbol_fails_closed(env, mt5):
    rec = make_instruction(symbol="AUDCAD.FX")     # canonical-valid, not at broker
    result = _produce(env, rec)
    assert result["status"] == ResultState.EXECUTION_FAILED
    assert result["reason_code"] == XReason.INVALID_SYMBOL
    assert len(mt5.order_log) == 0


def test_invalid_volume_fails_closed(env, mt5):
    env.default_volume = 999.0                      # above broker volume_max
    result = _produce(env, make_instruction())
    assert result["status"] == ResultState.EXECUTION_FAILED
    assert result["reason_code"] == XReason.INVALID_VOLUME
    assert len(mt5.order_log) == 0


# -- broker rejection outcomes ---------------------------------------------
def _reject_case(env, mt5, retcode, expect_reason):
    mt5.script(retcode)
    result = _produce(env, make_instruction())
    assert result["status"] == ResultState.EXECUTION_FAILED
    assert result["reason_code"] == expect_reason
    assert result["execution_error"]["retcode"] == retcode
    # failed execution archived to the rejected family; no open position
    assert (env.paths.archive_rejected /
            instruction_name("a1b2c3d4e5f60718")).exists()


def test_broker_rejection(env, mt5):
    _reject_case(env, mt5, mock_mt5.TRADE_RETCODE_REJECT, XReason.BROKER_REJECT)


def test_market_closed(env, mt5):
    _reject_case(env, mt5, mock_mt5.TRADE_RETCODE_MARKET_CLOSED, XReason.MARKET_CLOSED)


def test_requote_then_success(env, mt5):
    # M1: a transient REQUOTE is not terminal — a bounded resend (2nd attempt, no
    # queued failure left) fills. Duplicate-safe: only one position results.
    mt5.script(mock_mt5.TRADE_RETCODE_REQUOTE)     # one requote, then DONE by default
    result = _produce(env, make_instruction())
    assert result["status"] == ResultState.EXECUTED
    assert len(mt5.order_log) == 2                  # requote + successful resend
    assert mt5.position_by_comment("a1b2c3d4e5f60718") is not None


def test_off_quotes_then_success(env, mt5):
    mt5.script(mock_mt5.TRADE_RETCODE_PRICE_OFF)
    result = _produce(env, make_instruction())
    assert result["status"] == ResultState.EXECUTED
    assert len(mt5.order_log) == 2


def test_transient_persists_held_not_failed(env, mt5):
    # M1: transient every attempt -> NOT terminal EXECUTION_FAILED; held for
    # reconciliation (capacity-reserved), never dropped, never a phantom position.
    from forex_swing_orb.bridge.contract import ReasonCode
    mt5.script(*[mock_mt5.TRADE_RETCODE_REQUOTE] * 5)
    result = _produce(env, make_instruction())
    assert result["status"] == ReasonCode.RECONCILIATION_REQUIRED
    assert len(mt5.order_log) == 3                  # bounded to max_execution_attempts
    assert mt5.position_by_comment("a1b2c3d4e5f60718") is None
    # claimed instruction is HELD (no terminal result, not archived)
    assert (env.paths.claimed / instruction_name("a1b2c3d4e5f60718")).exists()
    assert not (env.paths.archive_rejected / instruction_name("a1b2c3d4e5f60718")).exists()


def test_trade_context_busy_ambiguous_held(env, mt5):
    # M1: TOO_MANY_REQUESTS is ambiguous/throttled -> never resent in-cycle; held.
    from forex_swing_orb.bridge.contract import ReasonCode
    mt5.script(mock_mt5.TRADE_RETCODE_TOO_MANY_REQUESTS)
    result = _produce(env, make_instruction())
    assert result["status"] == ReasonCode.RECONCILIATION_REQUIRED
    assert len(mt5.order_log) == 1                  # NOT hammered
    assert mt5.position_by_comment("a1b2c3d4e5f60718") is None


def test_terminal_disconnected_ambiguous_held(env, mt5):
    # M1: a disconnect during send is ambiguous (may have reached the server) ->
    # NEVER marked definitely-failed; held for broker-truth reconciliation.
    from forex_swing_orb.bridge.contract import ReasonCode
    mt5.connected = False
    result = _produce(env, make_instruction())
    assert result["status"] == ReasonCode.RECONCILIATION_REQUIRED
    assert len(mt5.order_log) == 1          # attempt logged, but no terminal drop
    assert (env.paths.claimed / instruction_name("a1b2c3d4e5f60718")).exists()


# -- duplicate prevention ---------------------------------------------------
def test_duplicate_instruction_not_reexecuted(env, mt5):
    rec = make_instruction()
    first = _produce(env, rec)
    assert first["status"] == ResultState.EXECUTED
    # re-deliver the SAME signal_id
    second = _produce(env, rec)
    assert second["status"] == ResultState.DUPLICATE
    assert len(mt5.order_log) == 1          # never a second order


def test_no_double_order_when_broker_already_holds(env, mt5):
    """Point-of-execution guard: if the broker already holds a position for the
    signal_id, adopt it — never resend — even without terminal bridge evidence."""
    rec = make_instruction()
    _write_pending(env.paths, rec)
    sid = env.claim_next(NOW)
    # broker already has a position tagged with this signal_id (prior attempt)
    mt5.positions[42] = mock_mt5.Position(
        ticket=42, symbol="EURUSD", type=mock_mt5.ORDER_TYPE_BUY, volume=0.10,
        price_open=1.1, sl=1.098, tp=1.104, comment=sid)
    result = env.process(sid, NOW)
    assert result["status"] == ResultState.EXECUTED
    assert result["reason_code"] == XReason.ADOPTED
    assert result["broker_order_id"] == 42
    assert len(mt5.order_log) == 0          # no new OrderSend


# -- restart recovery -------------------------------------------------------
def test_recovery_finalizes_from_broker(env, mt5):
    """Crash after OrderSend, before result write: broker holds the position,
    bridge has no result. Recovery writes EXECUTED from broker truth, no resend."""
    rec = _write_pending(env.paths, make_instruction())
    sid = rec["signal_id"]
    env.claim(sid, NOW)                                  # claimed, in flight
    env._write_ack(rec, NOW)                             # ack was written
    mt5.positions[99] = mock_mt5.Position(               # order reached broker
        ticket=99, symbol="EURUSD", type=mock_mt5.ORDER_TYPE_BUY, volume=0.10,
        price_open=1.10002, sl=rec["stop_loss"], tp=rec["take_profit"], comment=sid)

    summary = env.recover(NOW)
    assert summary["recovered_from_broker"] == 1
    assert summary["reprocessed"] == 0
    assert len(mt5.order_log) == 0                       # never resent
    result = _read_result(env.paths, sid, ResultState.EXECUTED)
    assert result["broker_order_id"] == 99
    assert result["reason_code"] == XReason.RECONCILE
    assert (env.paths.archive_accepted / instruction_name(sid)).exists()


def test_recovery_ack_but_no_broker_position_requires_reconciliation(env, mt5):
    """Crash after ack, before OrderSend reached the broker: outcome unknown.
    Fail closed to reconciliation-required; never resend."""
    rec = _write_pending(env.paths, make_instruction())
    sid = rec["signal_id"]
    env.claim(sid, NOW)
    env._write_ack(rec, NOW)                             # ack present, no position

    summary = env.recover(NOW)
    assert summary["reconciliation_required"] == 1
    assert len(mt5.order_log) == 0
    # no terminal result minted; claimed file stays for external reconciliation
    assert not list(env.paths.results.iterdir())
    assert (env.paths.claimed / instruction_name(sid)).exists()


def test_recovery_no_ack_reprocesses_safely(env, mt5):
    """Crash after claim, before ack: never attempted -> safe first execution."""
    rec = _write_pending(env.paths, make_instruction())
    sid = rec["signal_id"]
    env.claim(sid, NOW)                                  # claimed only

    summary = env.recover(NOW)
    assert summary["reprocessed"] == 1
    assert len(mt5.order_log) == 1                       # first (and only) order
    result = _read_result(env.paths, sid, ResultState.EXECUTED)
    assert result["broker_order_id"] is not None


def test_recovery_adopts_existing_terminal_no_resend(env, mt5):
    """Already terminal in the bridge + a stray claimed file -> adopt, no resend."""
    rec = make_instruction()
    _produce(env, rec)                                   # fully executed + archived
    sid = rec["signal_id"]
    # simulate a stray claimed file for the same signal_id
    atomic_write_text(env.paths.claimed / instruction_name(sid),
                      serialize.dumps(serialize.with_integrity_digest(rec)))

    summary = env.recover(NOW)
    assert summary["adopted"] == 1
    assert len(mt5.order_log) == 1                       # unchanged from the 1 real order


def test_recovery_rebuilds_ticket_map_from_broker(env, mt5):
    rec = make_instruction()
    _produce(env, rec)
    ticket = mt5.position_by_comment(rec["signal_id"]).ticket
    env.active_tickets = {}                              # simulate memory loss
    env.recover(NOW)
    assert env.active_tickets.get(rec["signal_id"]) == ticket


# -- ticket reconciliation / position lookup / close detection -------------
def test_ticket_correlation_and_lookup(env, mt5):
    rec = make_instruction()
    result = _produce(env, rec)
    ticket = result["broker_order_id"]
    assert env.active_tickets[rec["signal_id"]] == ticket
    assert mt5.position_by_comment(rec["signal_id"]).ticket == ticket


def test_position_close_detection(env, mt5):
    rec = make_instruction()
    result = _produce(env, rec)
    ticket = result["broker_order_id"]
    assert mt5.position_by_comment(rec["signal_id"]) is not None
    close = mt5.position_close(ticket)
    assert close.ok
    # close detection: the position is no longer open at the broker
    assert mt5.position_by_comment(rec["signal_id"]) is None
    assert mt5.positions_get() == []


# -- audit generation -------------------------------------------------------
def test_audit_trail_records_lifecycle(env):
    rec = make_instruction()
    _produce(env, rec)
    actions = [(a["action"], a["outcome"]) for a in env.audit.read_all()]
    assert ("claim", "CLAIMED") in actions
    assert ("ack", "ACK") in actions
    assert ("process", ResultState.EXECUTED) in actions


def test_failure_produces_audit_and_reason(env, mt5):
    mt5.script(mock_mt5.TRADE_RETCODE_MARKET_CLOSED)
    _produce(env, make_instruction())
    rows = env.audit.read_all()
    assert any(r["action"] == "process" and r["outcome"] == ResultState.EXECUTION_FAILED
               for r in rows)


# -- boundary enforcement (static) -----------------------------------------
EA_DIR = Path(__file__).resolve().parents[1]
# Real networking call signatures (not prose): MQL5 web/socket/FTP/mail APIs and
# Python network libraries. Descriptive words like "no sockets" are allowed.
FORBIDDEN_NET = ("WebRequest(", "SocketCreate(", "SocketConnect(", "SocketSend(",
                 "SocketRead(", "SocketTlsHandshake(", "SendFTP(", "SendMail(",
                 "SendNotification(", "InternetOpen", "wininet", "://",
                 "import socket", "socket.socket", "urllib", "http.client",
                 "requests.get", "requests.post")


def test_no_networking_in_adapter_sources():
    for pattern in ("*.py", "*.mq5", "*.mqh"):
        for src in EA_DIR.glob(pattern):
            text = src.read_text()
            for token in FORBIDDEN_NET:
                assert token not in text, f"{src.name} contains forbidden '{token}'"


def test_ea_source_has_no_python_execution():
    for src in list(EA_DIR.glob("*.mq5")) + list(EA_DIR.glob("*.mqh")):
        text = src.read_text().lower()
        for token in ("shellexecute", "python", "system(", "wine"):
            assert token not in text, f"{src.name} shells out via '{token}'"


def test_ea_source_has_no_strategy_calculation():
    """The EA must not compute strategy values. Assert the shipped MQL5 source
    calls no indicator / price-series MT5 APIs — the machinery a strategy would
    need to compute trend/breakout/retest/etc. (checks real API tokens, not
    prose, so explanatory comments are allowed)."""
    banned = ("iMA(", "iRSI(", "iATR(", "iStochastic(", "iCustom(", "iBands(",
              "iMACD(", "CopyRates(", "CopyBuffer(", "CopyTicks(", "iClose(",
              "iHigh(", "iLow(", "iOpen(", "iBars(", "IndicatorCreate(")
    for src in list(EA_DIR.glob("*.mq5")) + list(EA_DIR.glob("*.mqh")):
        text = src.read_text()
        for token in banned:
            assert token not in text, f"{src.name} computes strategy via '{token}'"
