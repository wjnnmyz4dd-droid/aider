"""Deterministic Position Manager (Phase 4D) — the ONE stop-management subsystem.

Executes the frozen Phase 4C-R design (``forex_swing_orb/position/contract.py`` +
``spec.py``) against the MT5 terminal (real EA or the mock). It is the single
source of stop logic: break-even, profit-lock, structure trailing, manual-change
handling, reconciliation, restart recovery, and the canonical audit record.

Authority: it may inspect position/stop/volume/ticket/symbol, compute allowed
stop improvements from the frozen math, request an MT5 stop modification, verify
the broker outcome, audit, and recover. It never creates direction, opens a
trade, widens/loosens a stop, accepts an AI-proposed stop, bypasses
reconciliation, or blindly retries an uncertain modification. All arithmetic and
invariants come from the frozen modules — nothing is recomputed here.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import append_line_fsync
from ..position import contract as PC
from ..position import spec
from ..position.contract import (StopPhase, PMReason, ManualAction,
                                 DEFAULT_PM_CONFIG, build_audit_record,
                                 stop_move_is_legal, risk_not_increased,
                                 phase_transition_is_legal, classify_manual_change)
from . import mock_mt5 as mt5c

# Deterministic broker-constraint retcodes (definite refusal, no blind retry).
_CONSTRAINT = frozenset({
    mt5c.TRADE_RETCODE_REJECT, mt5c.TRADE_RETCODE_INVALID_STOPS,
    mt5c.TRADE_RETCODE_REQUOTE, mt5c.TRADE_RETCODE_PRICE_OFF,
    mt5c.TRADE_RETCODE_MARKET_CLOSED, mt5c.TRADE_RETCODE_INVALID_VOLUME,
    mt5c.TRADE_RETCODE_INVALID_PRICE, mt5c.TRADE_RETCODE_TRADE_DISABLED,
})


class PMAudit:
    """Append-only, deterministic, canonical PM audit log (a recovery source)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record):
        append_line_fsync(self.path, serialize.canonical_json(record))
        return record

    def read_all(self):
        out = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if raw:
                        out.append(json.loads(raw))
        except FileNotFoundError:
            pass
        return out

    def records_for(self, signal_id):
        return [r for r in self.read_all() if r.get("signal_id") == signal_id]


class PositionManager:
    def __init__(self, mt5, audit_path, cfg=DEFAULT_PM_CONFIG):
        self.mt5 = mt5
        self.audit = PMAudit(audit_path)
        self.cfg = cfg
        self.states = {}                 # signal_id -> state (in-memory CACHE only)
        self._ticket_owner = {}          # ticket -> signal_id (duplicate guard)

    # -- registration -------------------------------------------------------
    def register(self, signal_id, ticket, symbol, direction, entry, initial_stop,
                 take_profit, now):
        R = spec.initial_risk(direction, entry, initial_stop)
        if R is None:                    # zero/negative/non-finite/wrong-sided
            self._emit(self._bare(signal_id, ticket, symbol, direction, entry,
                                  initial_stop), PMReason.DATA_INSUFFICIENT, now)
            return None
        if ticket in self._ticket_owner and self._ticket_owner[ticket] != signal_id:
            self._emit(self._bare(signal_id, ticket, symbol, direction, entry,
                                  initial_stop), PMReason.RECONCILIATION_REQUIRED, now,
                       reconciliation_status="duplicate_ticket")
            return None
        st = PC.build_state(signal_id, ticket, symbol, direction, entry,
                            initial_stop, take_profit, serialize.iso_utc(now))
        st["last_structure_ref"] = None
        st["volume"] = None
        try:
            pos = self.mt5.position_by_ticket(ticket)
            st["volume"] = pos.volume if pos is not None else None
        except mt5c.MT5Disconnected:
            st["volume"] = None
        self.states[signal_id] = st
        self._ticket_owner[ticket] = signal_id
        self._emit(st, PMReason.INITIAL, now, applied_stop=initial_stop)
        return st

    # -- one evaluation cycle (frozen precedence) ---------------------------
    def evaluate(self, signal_id, *, market_price=None, confirmed_swing=None,
                 structure_reference=None, bars_since_swing=None, now=None,
                 kill_switch=False, bars_open=None):
        st = self.states.get(signal_id)
        if st is None:
            return self._emit(self._bare(signal_id, None, None, None, None, None),
                              PMReason.RECONCILIATION_REQUIRED, now,
                              reconciliation_status="unknown_signal")
        if bars_open is not None:
            st["bars_open"] = bars_open
        R = spec.initial_risk(st["direction"], st["entry"], st["initial_stop"])
        if R is None:
            return self._emit(st, PMReason.DATA_INSUFFICIENT, now)

        # 1 broker reconciliation (+ 2 manual, 4 position-closed folded in)
        rec = self._reconcile(st, now)
        if rec is not None:
            return rec
        if st["phase"] == StopPhase.CLOSED:
            return self._emit(st, PMReason.POSITION_CLOSED, now)
        # 3 emergency kill switch
        if kill_switch:
            return self._protective_exit(st, PMReason.KILL_SWITCH, now)
        # 5 weekend policy
        if self._weekend_due(now):
            return self._protective_exit(st, PMReason.WEEKEND_EXIT, now)
        # 6 maximum duration
        if self._max_duration_due(st):
            return self._protective_exit(st, PMReason.MAX_DURATION_EXIT, now)
        # 7 protective_stop_integrity handled inside reconcile (never-loosen)
        # 8/9/10 management by phase; 11 no_action
        return self._manage(st, market_price, confirmed_swing, structure_reference,
                            bars_since_swing, R, now)

    # -- reconciliation (F6) ------------------------------------------------
    def _reconcile(self, st, now):
        try:
            if not self.mt5.terminal_connected():
                return self._emit(st, PMReason.DATA_STALE, now,
                                  reconciliation_status="terminal_disconnected")
            pos = self.mt5.position_by_ticket(st["ticket"])
        except mt5c.MT5Disconnected:
            return self._emit(st, PMReason.DATA_STALE, now,
                              reconciliation_status="terminal_disconnected")
        if pos is None:                                  # no broker position -> CLOSED
            st["phase"] = StopPhase.CLOSED
            return self._emit(st, PMReason.POSITION_CLOSED, now,
                              reconciliation_status="no_position")
        if pos.symbol != st["symbol"]:                   # symbol mismatch -> fail closed
            return self._emit(st, PMReason.RECONCILIATION_REQUIRED, now,
                              reconciliation_status="symbol_mismatch")
        if st.get("volume") is not None and pos.volume < st["volume"]:   # manual partial close
            st["volume"] = pos.volume                    # reconcile remaining; preserve stop
            return self._emit(st, PMReason.PARTIAL_CLOSED, now,
                              manual_status="partial_close",
                              reconciliation_status="partial_reconciled")
        broker_sl = pos.sl
        if broker_sl == st["current_stop"]:
            return None                                  # in sync -> continue
        observed = broker_sl if broker_sl not in (0, 0.0, None) else None
        action, reason = classify_manual_change(st["direction"], st["current_stop"],
                                                observed, position_present=True)
        if action == ManualAction.ADOPT:                 # tighter -> adopt broker truth
            prev = st["current_stop"]
            st["current_stop"] = broker_sl
            return self._emit(st, PMReason.MANUAL_CHANGE_ADOPTED, now, previous_stop=prev,
                              applied_stop=broker_sl, manual_status="tightened_adopted")
        # looser / removed -> reject and remediate by restoring protective stop
        return self._remediate(st, now, reason)

    def _remediate(self, st, now, reason):
        """Restore the protective (expected) stop after a manual loosening/removal.
        Never adopts the loosened value; audits the rejection."""
        expected = st["current_stop"]
        status, _res = self._broker_modify(st["ticket"], expected)
        if status == "done":
            return self._emit(st, reason, now, proposed_stop=expected,
                              applied_stop=expected, broker_result="DONE",
                              manual_status="loosening_rejected_restored",
                              reconciliation_status="remediated")
        if status == "constraint":
            return self._emit(st, PMReason.BROKER_CONSTRAINT, now, proposed_stop=expected,
                              manual_status="loosening_rejected", broker_result="CONSTRAINT")
        return self._emit(st, PMReason.RECONCILIATION_REQUIRED, now, proposed_stop=expected,
                          manual_status="loosening_rejected", broker_result="UNCERTAIN",
                          reconciliation_status="uncertain")

    # -- management: break-even / profit-lock / trailing --------------------
    def _manage(self, st, price, swing, swing_ref, bars_since, R, now):
        d, entry = st["direction"], st["entry"]
        cur = st["current_stop"]
        if price is None:
            return self._emit(st, PMReason.DATA_INSUFFICIENT, now)

        if st["phase"] == StopPhase.INITIAL:
            trig = spec.breakeven_trigger_price(d, entry, R, self.cfg)
            if not spec.breakeven_triggered(d, price, trig):
                return self._emit(st, PMReason.BREAKEVEN_PENDING, now,
                                  trigger_price=trig, market_reference=price)
            self._event(st, PMReason.BREAKEVEN_TRIGGERED, now,
                        trigger_price=trig, market_reference=price)
            cand = spec.breakeven_stop(d, entry, self.cfg)
            # protection already at/beyond BE (adopted / manual tighten): advance
            # phase without a redundant modification so later phases can engage.
            if self._at_or_beyond(d, cur, cand):
                st["phase"] = StopPhase.BREAKEVEN
                return self._emit(st, PMReason.BREAKEVEN_SET, now, trigger_price=trig,
                                  market_reference=price, reconciliation_status="already_protected")
            return self._try_advance(st, cand, PMReason.BREAKEVEN_SET, StopPhase.BREAKEVEN,
                                     price, trig, now)

        if st["phase"] == StopPhase.BREAKEVEN:
            trig = spec.profit_lock_trigger_price(d, entry, R, self.cfg)
            if not spec.profit_lock_triggered(d, price, trig):
                return self._emit(st, PMReason.NO_ACTION, now,
                                  trigger_price=trig, market_reference=price)
            self._event(st, PMReason.PROFIT_LOCK_TRIGGERED, now,
                        trigger_price=trig, market_reference=price)
            cand = spec.profit_lock_stop(d, entry, R, self.cfg)
            if self._at_or_beyond(d, cur, cand):
                st["phase"] = StopPhase.LOCKED
                return self._emit(st, PMReason.PROFIT_LOCK_SET, now, trigger_price=trig,
                                  market_reference=price, reconciliation_status="already_protected")
            return self._try_advance(st, cand, PMReason.PROFIT_LOCK_SET, StopPhase.LOCKED,
                                     price, trig, now)

        # LOCKED / TRAILING -> structure trailing
        return self._trail(st, price, swing, swing_ref, bars_since, now)

    def _try_advance(self, st, cand, ok_reason, next_phase, price, trig, now):
        d, cur = st["direction"], st["current_stop"]
        if not spec.is_stop_improvement(d, cur, cand, self.cfg):
            return self._emit(st, PMReason.TRAIL_NO_IMPROVEMENT, now,
                              trigger_price=trig, proposed_stop=cand, market_reference=price)
        if not spec.respects_broker_min_stop(d, price, cand, self.cfg):
            return self._emit(st, PMReason.BROKER_CONSTRAINT, now,
                              trigger_price=trig, proposed_stop=cand, market_reference=price)
        return self._apply_stop(st, cand, ok_reason, now, next_phase=next_phase,
                                trigger_price=trig, market_reference=price)

    def _trail(self, st, price, swing, swing_ref, bars_since, now):
        d, cur = st["direction"], st["current_stop"]
        if swing is None or swing_ref is None:
            return self._emit(st, PMReason.TRAIL_PENDING, now, market_reference=price)
        if bars_since is not None and spec.structure_is_stale(bars_since, self.cfg):
            return self._emit(st, PMReason.DATA_STALE, now,
                              structure_reference=swing_ref, market_reference=price)
        if swing_ref == st.get("last_structure_ref"):        # no repeat for same structure
            return self._emit(st, PMReason.TRAIL_NO_IMPROVEMENT, now,
                              structure_reference=swing_ref, market_reference=price)
        cand = spec.trailing_stop_candidate(d, swing, self.cfg)
        if cand is None:
            return self._emit(st, PMReason.DATA_INSUFFICIENT, now, market_reference=price)
        if not stop_move_is_legal(d, cur, cand):             # worse / backward
            return self._emit(st, self._reject_reason(st, cand), now,
                              proposed_stop=cand, structure_reference=swing_ref,
                              market_reference=price)
        if not spec.is_stop_improvement(d, cur, cand, self.cfg):
            return self._emit(st, PMReason.TRAIL_NO_IMPROVEMENT, now,
                              proposed_stop=cand, structure_reference=swing_ref,
                              market_reference=price)
        if not spec.respects_broker_min_stop(d, price, cand, self.cfg):
            return self._emit(st, PMReason.BROKER_CONSTRAINT, now,
                              proposed_stop=cand, structure_reference=swing_ref,
                              market_reference=price)
        rec = self._apply_stop(st, cand, PMReason.TRAIL_ADVANCED, now,
                               next_phase=StopPhase.TRAILING,
                               structure_reference=swing_ref, market_reference=price)
        if rec.get("applied_stop") is not None:
            st["last_structure_ref"] = swing_ref
        return rec

    # -- stop application (never widen/loosen; verify broker) ---------------
    def _apply_stop(self, st, proposed, ok_reason, now, next_phase=None,
                    trigger_price=None, structure_reference=None, market_reference=None):
        d, cur = st["direction"], st["current_stop"]
        if not stop_move_is_legal(d, cur, proposed):
            return self._emit(st, self._reject_reason(st, proposed), now,
                              proposed_stop=proposed, trigger_price=trigger_price,
                              structure_reference=structure_reference,
                              market_reference=market_reference)
        status, _res = self._broker_modify(st["ticket"], proposed)
        if status == "done":
            prev = st["current_stop"]
            st["current_stop"] = proposed
            if next_phase and phase_transition_is_legal(st["phase"], next_phase):
                st["phase"] = next_phase
            return self._emit(st, ok_reason, now, previous_stop=prev,
                              proposed_stop=proposed, applied_stop=proposed,
                              trigger_price=trigger_price,
                              structure_reference=structure_reference,
                              market_reference=market_reference, broker_result="DONE")
        if status == "constraint":
            return self._emit(st, PMReason.BROKER_CONSTRAINT, now, proposed_stop=proposed,
                              trigger_price=trigger_price, structure_reference=structure_reference,
                              market_reference=market_reference, broker_result="CONSTRAINT")
        # uncertain -> never advance, never blind retry
        return self._emit(st, PMReason.RECONCILIATION_REQUIRED, now, proposed_stop=proposed,
                          trigger_price=trigger_price, structure_reference=structure_reference,
                          market_reference=market_reference, broker_result="UNCERTAIN",
                          reconciliation_status="uncertain")

    def _at_or_beyond(self, direction, current, target):
        """True if the current stop is already at/beyond ``target`` in the
        protective direction (long: current >= target; short: current <= target)."""
        if str(direction).upper() in ("LONG", "BULLISH"):
            return current >= target
        return current <= target

    def _reject_reason(self, st, proposed):
        # WIDEN if the proposal exceeds the immutable initial risk; else LOOSEN.
        if not risk_not_increased(st["direction"], st["entry"], st["initial_stop"], proposed):
            return PMReason.STOP_WIDEN_REJECTED
        return PMReason.STOP_LOOSEN_REJECTED

    def _broker_modify(self, ticket, sl):
        """Returns 'done' | 'constraint' | 'uncertain'. Verifies broker truth on
        DONE; any exception/mismatch/unknown retcode is 'uncertain'."""
        try:
            res = self.mt5.modify_stop(ticket, sl)
        except mt5c.MT5Disconnected:
            return "uncertain", None
        if res.retcode == mt5c.TRADE_RETCODE_DONE:
            try:
                pos = self.mt5.position_by_ticket(ticket)
            except mt5c.MT5Disconnected:
                return "uncertain", res
            if pos is not None and pos.sl == sl:
                return "done", res
            return "uncertain", res
        if res.retcode in _CONSTRAINT:
            return "constraint", res
        return "uncertain", res

    # -- protective exit (weekend / max-duration / kill) --------------------
    def _protective_exit(self, st, reason, now):
        try:
            res = self.mt5.position_close(st["ticket"])
        except mt5c.MT5Disconnected:
            return self._emit(st, PMReason.RECONCILIATION_REQUIRED, now,
                              reconciliation_status="uncertain", broker_result="UNCERTAIN")
        if res.retcode == mt5c.TRADE_RETCODE_DONE:
            st["phase"] = StopPhase.CLOSED
            return self._emit(st, reason, now, broker_result="DONE")
        return self._emit(st, PMReason.RECONCILIATION_REQUIRED, now,
                          broker_result="CONSTRAINT")

    # -- weekend / max-duration (only if fully specified) -------------------
    def _weekend_due(self, now):
        if self.cfg.weekend_policy != PC.WeekendPolicy.FLATTEN or now is None:
            return False
        if not hasattr(now, "weekday"):
            return False
        wd = now.weekday()
        if wd > self.cfg.weekend_cutoff_dow:
            return True
        return wd == self.cfg.weekend_cutoff_dow and now.hour >= self.cfg.weekend_cutoff_hour_utc

    def _max_duration_due(self, st):
        return self.cfg.max_duration_bars > 0 and st["bars_open"] >= self.cfg.max_duration_bars

    # -- restart recovery ---------------------------------------------------
    def recover(self, signal_id, now):
        """Reconstruct state from the PM audit history + MT5 terminal truth (never
        RAM only). Phase never regresses; immutable R is recomputed from the
        immutable entry/initial_stop; the current stop is taken from broker truth
        (adopt tighter; flag reconciliation if broker is looser than audited)."""
        recs = self.audit.records_for(signal_id)
        if not recs:
            return None
        last = recs[-1]
        entry, istop = last["entry_price"], last["initial_stop"]
        direction, symbol, ticket = last["direction"], last["symbol"], last["ticket"]
        phase = max((r["phase"] for r in recs if r.get("phase") in StopPhase.ORDER),
                    key=lambda p: StopPhase.ORDER.index(p), default=StopPhase.INITIAL)
        audited_stop = next((r["applied_stop"] for r in reversed(recs)
                             if r.get("applied_stop") is not None), istop)
        try:
            connected = self.mt5.terminal_connected()
            pos = self.mt5.position_by_ticket(ticket) if connected else None
        except mt5c.MT5Disconnected:
            connected, pos = False, None
        st = PC.build_state(signal_id, ticket, symbol, direction, entry, istop,
                            last.get("take_profit"), last["evaluation_timestamp"], phase=phase)
        st["last_structure_ref"] = last.get("structure_reference")
        if not connected:
            self.states[signal_id] = st
            return self._emit(st, PMReason.DATA_STALE, now, restart_source="pm_audit_log",
                              reconciliation_status="terminal_disconnected")
        if pos is None:
            st["phase"] = StopPhase.CLOSED
            self.states[signal_id] = st
            return self._emit(st, PMReason.POSITION_CLOSED, now,
                              restart_source="mt5_terminal", reconciliation_status="no_position")
        broker_sl = pos.sl
        if stop_move_is_legal(direction, audited_stop, broker_sl):   # broker >= audited (tighter)
            st["current_stop"] = broker_sl
            reason, recon = PMReason.RECOVERED_FROM_BROKER, "synced"
        else:                                                         # broker looser than audited
            st["current_stop"] = audited_stop
            reason, recon = PMReason.RECONCILIATION_REQUIRED, "required"
        self.states[signal_id] = st
        self._ticket_owner[ticket] = signal_id
        self._emit(st, reason, now, applied_stop=st["current_stop"],
                   restart_source="mt5_terminal+pm_audit_log", reconciliation_status=recon)
        return st

    # -- audit helpers ------------------------------------------------------
    def _bare(self, signal_id, ticket, symbol, direction, entry, initial_stop):
        return {"signal_id": signal_id, "ticket": ticket, "symbol": symbol,
                "direction": direction, "entry": entry, "initial_stop": initial_stop,
                "current_stop": initial_stop, "phase": StopPhase.INITIAL}

    def _record(self, st, reason, now, **fields):
        R = spec.initial_risk(st.get("direction"), st.get("entry"), st.get("initial_stop"))
        base = build_audit_record(
            reason, serialize.iso_utc(now) if now is not None else None,
            signal_id=st.get("signal_id"), ticket=st.get("ticket"),
            symbol=st.get("symbol"), direction=st.get("direction"),
            phase=st.get("phase"), entry_price=st.get("entry"),
            initial_stop=st.get("initial_stop"), immutable_initial_R=R,
            previous_stop=st.get("current_stop"),
        )
        for k, v in fields.items():
            if k in base:
                base[k] = v
        # sanitize non-finite floats so the audit record always serializes
        # deterministically (fail-closed values become null, never NaN/Inf).
        import math as _math
        for k, v in base.items():
            if isinstance(v, float) and not _math.isfinite(v):
                base[k] = None
        return base

    def _emit(self, st, reason, now, **fields):
        rec = self._record(st, reason, now, **fields)
        return self.audit.emit(rec)

    def _event(self, st, reason, now, **fields):
        """A non-action event line (e.g. trigger armed); not the cycle outcome."""
        self.audit.emit(self._record(st, reason, now, **fields))
