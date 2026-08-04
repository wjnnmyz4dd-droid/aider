"""Reference Session Edge MT5 execution consumer (TEST HARNESS / reference impl).

This is the executable, testable **specification** of the Session Edge MT5
Execution Adapter, expressed in Python against a mock MT5 terminal. The shipped
adapter is the MQL5 Expert Advisor in ``SessionEdgeExecutionEA.mq5``; this module
mirrors its logic one-to-one so the execution protocol can be verified
deterministically on a platform with no MetaTrader terminal or MQL compiler.

It is an **execution adapter only**. It contains no strategy logic: no trend,
breakout, retest, price-action, Trend-Health, news, risk, stop or target
calculation, and it never decides or changes trade direction. Direction, entry,
stop, target and volume are read verbatim from the validated bridge instruction.

It is a bridge *consumer*: it reuses the accepted Filesystem Execution Bridge as
the single source of truth (the bridge's Consumer, SeenResolver, serializer,
validator, atomic writer, ledger, audit and archival). It adds only the two
things the bridge deliberately lacks because it has no broker: an MT5 order hook
and broker-aware restart recovery.

No networking of any kind: only the filesystem bridge and the (mock) MT5 API.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from ..bridge.consumer import Consumer
from ..bridge.contract import HookPosture, ReasonCode, ResultState, build_ack
from ..bridge.paths import ack_name, instruction_name, is_safe_regular_file, safe_read_text
from ..bridge.reconcile import _clean_tmp
from . import mock_mt5 as mt5c

# -- deterministic execution-layer reason codes -----------------------------
# The bridge owns transport reason codes (E_SCHEMA, E_INTEGRITY, E_DUP, ...).
# These cover only broker/MT5 outcomes the bridge cannot know about. Each is a
# pure function of the broker retcode or a pre-send broker check — no wall clock.
class XReason:
    OK = "X_OK"
    ADOPTED = "X_ADOPTED"                     # broker already holds the order (no resend)
    INVALID_SYMBOL = "X_INVALID_SYMBOL"       # symbol not tradable at this broker
    INVALID_VOLUME = "X_INVALID_VOLUME"       # volume outside broker min/max/step
    INVALID_STOPS = "X_INVALID_STOPS"         # SL/TP missing or rejected by broker
    BROKER_REJECT = "X_BROKER_REJECT"         # generic broker rejection
    MARKET_CLOSED = "X_MARKET_CLOSED"
    REQUOTE = "X_REQUOTE"
    OFF_QUOTES = "X_OFF_QUOTES"
    TRADE_BUSY = "X_TRADE_BUSY"               # trade context / subsystem busy
    NO_MONEY = "X_NO_MONEY"
    DISCONNECTED = "X_DISCONNECTED"           # terminal<->server link down
    BROKER_ERROR = "X_BROKER_ERROR"           # any other non-DONE retcode
    RECONCILE = "X_RECONCILE"                 # restart: attempted, outcome unknown


# broker retcode -> (reason code). Only DONE is success.
_RETCODE_REASON = {
    mt5c.TRADE_RETCODE_REJECT: XReason.BROKER_REJECT,
    mt5c.TRADE_RETCODE_MARKET_CLOSED: XReason.MARKET_CLOSED,
    mt5c.TRADE_RETCODE_REQUOTE: XReason.REQUOTE,
    mt5c.TRADE_RETCODE_PRICE_OFF: XReason.OFF_QUOTES,
    mt5c.TRADE_RETCODE_TOO_MANY_REQUESTS: XReason.TRADE_BUSY,
    mt5c.TRADE_RETCODE_TIMEOUT: XReason.TRADE_BUSY,
    mt5c.TRADE_RETCODE_INVALID_VOLUME: XReason.INVALID_VOLUME,
    mt5c.TRADE_RETCODE_INVALID_STOPS: XReason.INVALID_STOPS,
    mt5c.TRADE_RETCODE_INVALID_PRICE: XReason.OFF_QUOTES,
    mt5c.TRADE_RETCODE_NO_MONEY: XReason.NO_MONEY,
    mt5c.TRADE_RETCODE_TRADE_DISABLED: XReason.MARKET_CLOSED,
    mt5c.TRADE_RETCODE_CONNECTION: XReason.DISCONNECTED,
}

_DIRECTION_TO_ORDER_TYPE = {"LONG": mt5c.ORDER_TYPE_BUY, "SHORT": mt5c.ORDER_TYPE_SELL}


def normalize_symbol(canonical, broker_suffix=""):
    """Map a canonical bridge symbol (``EURUSD.FX``) to the broker's symbol.

    Pure string normalization — NOT strategy logic. The canonical ``.FX`` suffix
    is a bridge convention; brokers expose the base pair, optionally with their
    own suffix (e.g. ``EURUSD``, ``EURUSD.raw``). Returns None if the input is
    not a canonical ``.FX`` symbol.
    """
    if not isinstance(canonical, str) or not canonical.endswith(".FX"):
        return None
    base = canonical[:-3]
    if len(base) != 6 or not base.isalpha() or not base.isupper():
        return None
    return base + broker_suffix


class ExecutionConsumer:
    """Session Edge MT5 execution adapter (reference). Wraps a bridge Consumer
    with an MT5 order hook (posture NON_IDEMPOTENT_EXECUTION) and broker-aware
    recovery. Holds only transient runtime state; the bridge is authoritative."""

    def __init__(self, paths, cfg, ledger, audit, mt5, resolver=None,
                 broker_suffix="", ea_id="SessionEdgeExecutionEA/1.0",
                 default_volume=0.10):
        self.mt5 = mt5
        self.broker_suffix = broker_suffix
        self.ea_id = ea_id
        # Operator-configured constant lot. The EA NEVER sizes trades from risk;
        # see _resolve_volume. This is a broker/account operational input, not a
        # strategy decision.
        self.default_volume = default_volume
        # transient, non-authoritative runtime correlation: signal_id -> ticket.
        # Rebuilt from the bridge + MT5 on restart; never trusted for correctness.
        self.active_tickets = {}
        self.consumer = Consumer(paths, cfg, ledger, audit, hook=self._execute,
                                 hook_posture=HookPosture.NON_IDEMPOTENT_EXECUTION,
                                 resolver=resolver)

    # convenience passthroughs to the bridge consumer -----------------------
    @property
    def paths(self):
        return self.consumer.paths

    @property
    def audit(self):
        return self.consumer.audit

    @property
    def resolver(self):
        return self.consumer.resolver

    def claim(self, signal_id, now):
        return self.consumer.claim(signal_id, now)

    def claim_next(self, now):
        return self.consumer.claim_next(now)

    def process(self, signal_id, now):
        return self.consumer.process(signal_id, now)

    def process_next(self, now):
        sid = self.claim_next(now)
        return self.process(sid, now) if sid else None

    # -- acknowledgement ----------------------------------------------------
    def _write_ack(self, record, now, extra=None):
        """Write the deterministic acknowledgement the moment execution
        ownership is accepted (after validation, before OrderSend). Non-terminal;
        records EA identity + MT5 terminal identity so a restart can tell an
        execution attempt was in flight for this signal_id."""
        signal_id = record["signal_id"]
        ack_id = serialize.result_id(signal_id, "ACK")
        detail = {
            "ea_id": self.ea_id,
            "mt5_account_id": getattr(self.mt5, "account_id", None),
            "mt5_terminal_id": getattr(self.mt5, "terminal_id", None),
            "terminal_state": "ACK",
        }
        if extra:
            detail.update(extra)
        ack = build_ack(signal_id, ack_id, serialize.iso_utc(now),
                        instruction=record, detail=detail)
        atomic_write_text(self.paths.acks / ack_name(signal_id, ack_id),
                          serialize.dumps(ack))
        self.audit.emit(serialize.iso_utc(now), "ack", "ACK",
                        signal_id=signal_id, detail={"ack_id": ack_id})
        return ack

    def _has_ack(self, signal_id):
        ack_id = serialize.result_id(signal_id, "ACK")
        return (self.paths.acks / ack_name(signal_id, ack_id)).exists()

    # -- the MT5 order hook (called by the bridge Consumer after validation) --
    def _execute(self, record, now):
        """Place exactly one market order for a validated instruction. Returns
        (state, reason_code, detail) for the bridge's single terminal writer.
        Never computes strategy values — direction/entry/stop/target/volume come
        straight from the instruction. Fails closed on any broker error."""
        signal_id = record["signal_id"]

        # No-double-order guard at the point of execution: if the broker already
        # holds a position tagged with this signal_id, adopt it — never resend.
        try:
            existing = self.mt5.position_by_comment(signal_id)
        except mt5c.MT5Disconnected:
            self._write_ack(record, now, extra={"note": "disconnected_precheck"})
            return ResultState.EXECUTION_FAILED, XReason.DISCONNECTED, {
                "execution": {"execution_error": "terminal_disconnected"}}
        if existing is not None:
            return self._executed_detail(record, existing, XReason.ADOPTED, now,
                                         adopted=True)

        # Ownership accepted -> write the acknowledgement before any order.
        self._write_ack(record, now)

        # Broker-specific input checks (NOT strategy checks): symbol tradable,
        # volume within broker limits, stops present. Strategy geometry was
        # already validated by the bridge; these are the broker's constraints.
        broker_symbol = normalize_symbol(record["symbol"], self.broker_suffix)
        info = self.mt5.symbol_info(broker_symbol) if broker_symbol else None
        if info is None or info.trade_mode == mt5c.SYMBOL_TRADE_MODE_DISABLED:
            return self._fail(signal_id, XReason.INVALID_SYMBOL,
                              {"symbol": record["symbol"], "broker_symbol": broker_symbol})
        vol = self._resolve_volume(record)
        bad_vol = self._volume_error(vol, info)
        if bad_vol is not None:
            return self._fail(signal_id, XReason.INVALID_VOLUME,
                              {"volume": vol, "reason": bad_vol})
        if record.get("stop_loss") is None or record.get("take_profit") is None:
            return self._fail(signal_id, XReason.INVALID_STOPS,
                              {"stop_loss": record.get("stop_loss"),
                               "take_profit": record.get("take_profit")})

        order_type = _DIRECTION_TO_ORDER_TYPE[record["direction"]]
        request = {
            "symbol": broker_symbol,
            "volume": vol,
            "type": order_type,
            "price": record["entry_price"],
            "sl": record["stop_loss"],
            "tp": record["take_profit"],
            "comment": signal_id,          # ticket <-> signal_id correlation
        }
        try:
            res = self.mt5.order_send(request)
        except mt5c.MT5Disconnected:
            return self._fail(signal_id, XReason.DISCONNECTED,
                              {"execution_error": "terminal_disconnected"})

        if not res.ok:
            reason = _RETCODE_REASON.get(res.retcode, XReason.BROKER_ERROR)
            return ResultState.EXECUTION_FAILED, reason, {
                "execution": {
                    "broker_order_id": None,
                    "requested_price": record["entry_price"],
                    "requested_volume": vol,
                    "filled_price": None,
                    "filled_volume": None,
                    "slippage": None,
                    "execution_error": {"retcode": res.retcode, "comment": res.comment},
                }}

        self.active_tickets[signal_id] = res.order
        pos = self.mt5.position_by_comment(signal_id)
        return self._executed_detail(record, pos, XReason.OK, now, result=res)

    # -- helpers ------------------------------------------------------------
    def _resolve_volume(self, record):
        """Resolve the order volume WITHOUT any risk math. The EA never sizes
        trades: it uses an explicit instruction ``volume`` when the upstream risk
        layer provides one, else an operator-configured constant lot. It NEVER
        converts ``risk_fraction`` to lots — that is risk sizing, which the EA
        must not perform. (The frozen v1.4.0 instruction contract carries
        ``risk_fraction`` but no executable volume; see README 'Deviations'.)"""
        if record.get("volume") is not None:
            return record["volume"]
        return self.default_volume

    def _volume_error(self, vol, info):
        if vol is None or not isinstance(vol, (int, float)):
            return "missing"
        if vol < info.volume_min or vol > info.volume_max:
            return "out_of_range"
        # step check with float tolerance
        steps = round((vol - info.volume_min) / info.volume_step)
        nearest = info.volume_min + steps * info.volume_step
        if abs(nearest - vol) > info.volume_step * 1e-6:
            return "off_step"
        return None

    def _executed_detail(self, record, pos, reason, now, result=None,
                         adopted=False):
        signal_id = record["signal_id"]
        ticket = pos.ticket if pos is not None else (result.order if result else None)
        filled_price = pos.price_open if pos is not None else (
            result.price if result else None)
        volume = pos.volume if pos is not None else (
            result.volume if result else self._resolve_volume(record))
        slippage = None
        if filled_price is not None and record.get("entry_price") is not None:
            slippage = round(filled_price - record["entry_price"], 10)
        if signal_id is not None and ticket is not None:
            self.active_tickets[signal_id] = ticket
        detail = {
            "adopted": adopted,
            "ticket": ticket,
            "symbol": record.get("symbol"),
            "direction": record.get("direction"),
            "execution": {
                "broker_order_id": ticket,
                "requested_price": record.get("entry_price"),
                "filled_price": filled_price,
                "requested_volume": self._resolve_volume(record),
                "filled_volume": volume,
                "slippage": slippage,
                "execution_error": None,
            },
        }
        return ResultState.EXECUTED, reason, detail

    def _fail(self, signal_id, reason, extra):
        return ResultState.EXECUTION_FAILED, reason, {
            "execution": {"execution_error": extra}}

    # -- broker-aware restart recovery --------------------------------------
    def recover(self, now):
        """Deterministic restart recovery. Reconstructs working state from the
        filesystem bridge + the MT5 terminal — never from memory. Guarantees no
        second order is ever submitted for a signal_id.

        Per stranded claimed instruction:
          * bridge terminal evidence  -> adopt it (bridge machinery, no resend)
          * conflicting evidence      -> quarantine (fail closed)
          * broker holds the order    -> finalize EXECUTED from broker truth
          * ack present, no broker pos -> reconciliation-required (attempted,
                                          outcome unknown; never resend)
          * no ack, no broker pos      -> safe first execution (process normally)
        """
        c = self.consumer
        paths, audit = c.paths, c.audit
        summary = {"tmp_cleaned": 0, "adopted": 0, "recovered_from_broker": 0,
                   "reconciliation_required": 0, "reprocessed": 0, "quarantined": 0}

        for d in (paths.pending, paths.claimed, paths.results, paths.acks):
            summary["tmp_cleaned"] += _clean_tmp(d, audit, now)

        # Rebuild the transient ticket<->signal_id correlation from the MT5
        # terminal (a source of truth), not from any in-memory carryover.
        self.active_tickets = self._rebuild_ticket_map()

        claimed = sorted(paths.claimed.iterdir()) if paths.claimed.exists() else []
        for p in claimed:
            if p.name.startswith(".") and p.name.endswith(".tmp"):
                continue
            if not is_safe_regular_file(p, paths.root) or len(p.name) != 21 or \
                    not p.name.endswith(".json"):
                c._quarantine(p, p.name[:-5], now, ReasonCode.E_UNSAFE_PATH)
                summary["quarantined"] += 1
                continue
            sid = p.name[:-5]
            seen = self.resolver.resolve(sid)
            if seen.conflict:
                c._quarantine(p, sid, now, ReasonCode.E_CONFLICT, detail=seen.detail)
                summary["quarantined"] += 1
                continue
            if seen.terminal:
                c._adopt(sid, seen, now, action="reconcile")
                summary["adopted"] += 1
                continue

            # not terminal in the bridge: consult the broker (the other source
            # of truth) before deciding — never a blind resend.
            pos = self._broker_position(sid)
            if pos is not None:
                self._finalize_from_broker(sid, p, pos, now)
                summary["recovered_from_broker"] += 1
            elif self._has_ack(sid):
                c.mark_reconciliation_required(sid, now)
                summary["reconciliation_required"] += 1
            else:
                self.process(sid, now)          # never attempted -> safe to run
                summary["reprocessed"] += 1

        audit.emit(serialize.iso_utc(now), "reconcile", "EXEC_DONE", detail=summary)
        return summary

    def _rebuild_ticket_map(self):
        """Reconstruct signal_id -> ticket from open MT5 positions (broker truth).
        Positions are tagged with their signal_id in the order comment."""
        mapping = {}
        try:
            for pos in self.mt5.positions_get():
                if pos.comment:
                    mapping[pos.comment] = pos.ticket
        except mt5c.MT5Disconnected:
            pass
        return mapping

    def _broker_position(self, signal_id):
        try:
            return self.mt5.position_by_comment(signal_id)
        except mt5c.MT5Disconnected:
            return None

    def _finalize_from_broker(self, signal_id, claimed_path, pos, now):
        """The broker holds a position for this signal_id but the bridge has no
        terminal result (crash between OrderSend and result-write). Write the
        EXECUTED result from broker truth via the bridge's single terminal
        writer — one result, then archive. Never resends."""
        ok, text, _ = safe_read_text(claimed_path, self.paths.root,
                                     self.consumer.cfg.max_instruction_bytes)
        record = {}
        if ok:
            parsed, rec = serialize.loads(text)
            if parsed:
                record = rec
        record.setdefault("signal_id", signal_id)
        _, reason, detail = self._executed_detail(record, pos, XReason.RECONCILE, now)
        received_iso = serialize.iso_utc(now)
        return self.consumer._finish(signal_id, now, received_iso,
                                     ResultState.EXECUTED, reason, record, detail)
