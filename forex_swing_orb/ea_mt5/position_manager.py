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
import math
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

# F2: quantization defaults when the broker symbol has no tick metadata.
_FALLBACK_DIGITS = 5              # 5-digit FX default (point = 1e-5)
_TICK_TOLERANCE = 0              # allowed deviation in ticks for stop equality


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
        # F2: compare on the symbol tick grid so benign broker normalization is
        # NOT mistaken for a manual change.
        if broker_sl not in (0, 0.0, None) and self._eq_stop(broker_sl, st["current_stop"], st["symbol"]):
            return None                                  # in sync -> continue
        observed = broker_sl if broker_sl not in (0, 0.0, None) else None
        action, reason = classify_manual_change(st["direction"], st["current_stop"],
                                                observed, position_present=True)
        if action == ManualAction.ADOPT:                 # tighter -> adopt broker truth
            prev = st["current_stop"]
            st["current_stop"] = self._q(broker_sl, st["symbol"])
            return self._emit(st, PMReason.MANUAL_CHANGE_ADOPTED, now, previous_stop=prev,
                              applied_stop=st["current_stop"], manual_status="tightened_adopted")
        # looser / removed -> reject and remediate by restoring protective stop
        return self._remediate(st, now, reason)

    def _remediate(self, st, now, reason):
        """Restore the protective (expected) stop after a manual loosening/removal.
        Never adopts the loosened value; audits the rejection."""
        expected = self._q(st["current_stop"], st["symbol"])
        status, _res = self._broker_modify(st["ticket"], expected, st["symbol"])
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
        sym = st["symbol"]
        if price is None:
            return self._emit(st, PMReason.DATA_INSUFFICIENT, now)

        if st["phase"] == StopPhase.INITIAL:
            trig = spec.breakeven_trigger_price(d, entry, R, self.cfg)
            if not self._reached_q(d, price, trig, sym):
                return self._emit(st, PMReason.BREAKEVEN_PENDING, now,
                                  trigger_price=trig, market_reference=price)
            self._event(st, PMReason.BREAKEVEN_TRIGGERED, now,
                        trigger_price=trig, market_reference=price)
            cand = self._q(spec.breakeven_stop(d, entry, self.cfg), sym)
            # protection already at/beyond BE (adopted / manual tighten): advance
            # phase without a redundant modification so later phases can engage.
            if self._at_or_beyond_q(d, cur, cand, sym):
                st["phase"] = StopPhase.BREAKEVEN
                return self._emit(st, PMReason.BREAKEVEN_SET, now, trigger_price=trig,
                                  market_reference=price, reconciliation_status="already_protected")
            return self._try_advance(st, cand, PMReason.BREAKEVEN_SET, StopPhase.BREAKEVEN,
                                     price, trig, now)

        if st["phase"] == StopPhase.BREAKEVEN:
            trig = spec.profit_lock_trigger_price(d, entry, R, self.cfg)
            if not self._reached_q(d, price, trig, sym):
                return self._emit(st, PMReason.NO_ACTION, now,
                                  trigger_price=trig, market_reference=price)
            self._event(st, PMReason.PROFIT_LOCK_TRIGGERED, now,
                        trigger_price=trig, market_reference=price)
            cand = self._q(spec.profit_lock_stop(d, entry, R, self.cfg), sym)
            if self._at_or_beyond_q(d, cur, cand, sym):
                st["phase"] = StopPhase.LOCKED
                return self._emit(st, PMReason.PROFIT_LOCK_SET, now, trigger_price=trig,
                                  market_reference=price, reconciliation_status="already_protected")
            return self._try_advance(st, cand, PMReason.PROFIT_LOCK_SET, StopPhase.LOCKED,
                                     price, trig, now)

        # LOCKED / TRAILING -> structure trailing
        return self._trail(st, price, swing, swing_ref, bars_since, now)

    def _try_advance(self, st, cand, ok_reason, next_phase, price, trig, now):
        d, cur, sym = st["direction"], st["current_stop"], st["symbol"]
        if not self._improves_q(d, cur, cand, sym):
            return self._emit(st, PMReason.TRAIL_NO_IMPROVEMENT, now,
                              trigger_price=trig, proposed_stop=cand, market_reference=price)
        if not self._min_stop_ok_q(d, price, cand, sym):
            return self._emit(st, PMReason.BROKER_CONSTRAINT, now,
                              trigger_price=trig, proposed_stop=cand, market_reference=price)
        return self._apply_stop(st, cand, ok_reason, now, next_phase=next_phase,
                                trigger_price=trig, market_reference=price)

    def _trail(self, st, price, swing, swing_ref, bars_since, now):
        d, cur, sym = st["direction"], st["current_stop"], st["symbol"]
        if swing is None or swing_ref is None:
            return self._emit(st, PMReason.TRAIL_PENDING, now, market_reference=price)
        # F6: structure freshness is mandatory for a trailing move.
        if bars_since is None or spec.structure_is_stale(bars_since, self.cfg):
            return self._emit(st, PMReason.DATA_STALE, now,
                              structure_reference=swing_ref, market_reference=price)
        if swing_ref == st.get("last_structure_ref"):        # no repeat for same structure
            return self._emit(st, PMReason.TRAIL_NO_IMPROVEMENT, now,
                              structure_reference=swing_ref, market_reference=price)
        cand = spec.trailing_stop_candidate(d, swing, self.cfg)
        if cand is None:
            return self._emit(st, PMReason.DATA_INSUFFICIENT, now, market_reference=price)
        cand = self._q(cand, sym)
        if not self._legal_q(d, cur, cand, sym):             # worse / backward
            return self._emit(st, self._reject_reason(st, cand), now,
                              proposed_stop=cand, structure_reference=swing_ref,
                              market_reference=price)
        if not self._improves_q(d, cur, cand, sym):
            return self._emit(st, PMReason.TRAIL_NO_IMPROVEMENT, now,
                              proposed_stop=cand, structure_reference=swing_ref,
                              market_reference=price)
        if not self._min_stop_ok_q(d, price, cand, sym):
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
        d, cur, sym = st["direction"], st["current_stop"], st["symbol"]
        proposed = self._q(proposed, sym)                     # F2: send a tick-grid value
        if not self._legal_q(d, cur, proposed, sym):
            return self._emit(st, self._reject_reason(st, proposed), now,
                              proposed_stop=proposed, trigger_price=trigger_price,
                              structure_reference=structure_reference,
                              market_reference=market_reference)
        common = dict(trigger_price=trigger_price, structure_reference=structure_reference,
                      market_reference=market_reference)
        # F1: record modification INTENT before touching the broker. If the intent
        # audit cannot be written, FAIL CLOSED — do not modify the stop.
        intent = self._record(st, ok_reason, now, proposed_stop=proposed,
                              broker_result="INTENT", reconciliation_status="intent", **common)
        if not self._safe_emit(intent):
            return self._record(st, PMReason.RECONCILIATION_REQUIRED, now, proposed_stop=proposed,
                                broker_result="NOT_ATTEMPTED",
                                reconciliation_status="audit_intent_failed", **common)
        status, _res = self._broker_modify(st["ticket"], proposed, sym)
        if status == "done":
            prev = st["current_stop"]
            st["current_stop"] = proposed
            if next_phase and phase_transition_is_legal(st["phase"], next_phase):
                st["phase"] = next_phase
            rec = self._record(st, ok_reason, now, previous_stop=prev, proposed_stop=proposed,
                               applied_stop=proposed, broker_result="DONE", **common)
            if not self._safe_emit(rec):
                # F1: broker applied but the completion audit failed. Never throw;
                # flag reconciliation. Broker truth is intact (state + broker hold
                # the applied stop) and is rebuilt cleanly on the next cycle.
                self._safe_emit(self._record(st, PMReason.RECONCILIATION_REQUIRED, now,
                                applied_stop=proposed, broker_result="DONE",
                                reconciliation_status="completion_audit_failed", **common))
            return rec
        if status == "constraint":
            return self._emit(st, PMReason.BROKER_CONSTRAINT, now, proposed_stop=proposed,
                              broker_result="CONSTRAINT", **common)
        # uncertain -> never advance, never blind retry
        return self._emit(st, PMReason.RECONCILIATION_REQUIRED, now, proposed_stop=proposed,
                          broker_result="UNCERTAIN", reconciliation_status="uncertain", **common)

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

    def _broker_modify(self, ticket, sl, symbol):
        """Returns 'done' | 'constraint' | 'uncertain'. On DONE, verifies broker
        truth on the SYMBOL TICK GRID (F2 — benign normalization still verifies);
        any exception / tick mismatch / unknown retcode is 'uncertain'."""
        try:
            res = self.mt5.modify_stop(ticket, sl)
        except mt5c.MT5Disconnected:
            return "uncertain", None
        if res.retcode == mt5c.TRADE_RETCODE_DONE:
            try:
                pos = self.mt5.position_by_ticket(ticket)
            except mt5c.MT5Disconnected:
                return "uncertain", res
            if pos is not None and self._eq_stop(pos.sl, sl, symbol):
                return "done", res
            return "uncertain", res
        if res.retcode in _CONSTRAINT:
            return "constraint", res
        return "uncertain", res

    # -- protective exit (weekend / max-duration / kill) --------------------
    def _protective_exit(self, st, reason, now):
        try:
            # R3: pass the (already-computed) protective reason to the broker seam so
            # a bridge-backed adapter can authorize the close. Non-arithmetic plumbing;
            # the mock/real terminal ignore the kwarg. No change to triggers/precedence.
            res = self.mt5.position_close(st["ticket"], reason=reason)
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
        if self._legal_q(direction, audited_stop, broker_sl, symbol):   # broker >= audited (tighter)
            st["current_stop"] = self._q(broker_sl, symbol)
            reason, recon = PMReason.RECOVERED_FROM_BROKER, "synced"
        else:                                                         # broker looser than audited
            st["current_stop"] = self._q(audited_stop, symbol)
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
        for k, v in base.items():
            if isinstance(v, float) and not math.isfinite(v):
                base[k] = None
        return base

    def _safe_emit(self, rec):
        """Append an audit record; return True on success, False on any IO error
        (F1: audit writes NEVER raise out of the manager)."""
        try:
            self.audit.emit(rec)
            return True
        except Exception:
            return False

    def _emit(self, st, reason, now, **fields):
        rec = self._record(st, reason, now, **fields)
        self._safe_emit(rec)
        return rec

    def _event(self, st, reason, now, **fields):
        """A non-action event line (e.g. trigger armed); not the cycle outcome."""
        self._safe_emit(self._record(st, reason, now, **fields))

    # -- F2: symbol-tick quantization + tolerant comparison -----------------
    def _point(self, symbol):
        try:
            info = self.mt5.symbol_info(symbol)
            if info is not None and getattr(info, "point", None):
                return float(info.point)
        except Exception:
            pass
        return 10.0 ** (-_FALLBACK_DIGITS)

    def _digits(self, symbol):
        p = self._point(symbol)
        return max(0, int(round(-math.log10(p)))) if p > 0 else _FALLBACK_DIGITS

    def _q(self, value, symbol):
        """Quantize (normalize) a price to the symbol's tick grid (NormalizeDouble
        analog). Returns value unchanged if non-finite."""
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return value
        return round(value, self._digits(symbol))

    def _ticks(self, value, symbol):
        return int(round(value / self._point(symbol)))

    def _eq_stop(self, a, b, symbol):
        """Tolerant equality in tick space (absorbs broker normalization)."""
        if a is None or b is None:
            return a is b
        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        return abs(self._ticks(a, symbol) - self._ticks(b, symbol)) <= _TICK_TOLERANCE

    def _legal_q(self, direction, current, candidate, symbol):
        """Never-widen/never-loosen in tick space (equal = allowed)."""
        ct, nt = self._ticks(current, symbol), self._ticks(candidate, symbol)
        if str(direction).upper() in ("LONG", "BULLISH"):
            return nt >= ct
        return nt <= ct

    def _improves_q(self, direction, current, candidate, symbol):
        """Strict improvement by >= min_trail_improvement, in tick space (fixes
        exact-boundary double rounding)."""
        ct, nt = self._ticks(current, symbol), self._ticks(candidate, symbol)
        thresh = max(1, int(round(self.cfg.min_trail_improvement_pips
                                  * self.cfg.pip_size / self._point(symbol))))
        if str(direction).upper() in ("LONG", "BULLISH"):
            return (nt - ct) >= thresh
        return (ct - nt) >= thresh

    def _min_stop_ok_q(self, direction, price, candidate, symbol):
        if self.cfg.broker_min_stop_pips <= 0:
            return True
        dist = int(round(self.cfg.broker_min_stop_pips * self.cfg.pip_size / self._point(symbol)))
        pt, nt = self._ticks(price, symbol), self._ticks(candidate, symbol)
        if str(direction).upper() in ("LONG", "BULLISH"):
            return (pt - nt) >= dist
        return (nt - pt) >= dist

    def _reached_q(self, direction, price, trigger, symbol):
        """Trigger comparison (>= toward profit) in tick space."""
        if trigger is None or not math.isfinite(price):
            return False
        pt, tt = self._ticks(price, symbol), self._ticks(trigger, symbol)
        if str(direction).upper() in ("LONG", "BULLISH"):
            return pt >= tt
        return pt <= tt

    def _at_or_beyond_q(self, direction, current, target, symbol):
        ct, tt = self._ticks(current, symbol), self._ticks(target, symbol)
        if str(direction).upper() in ("LONG", "BULLISH"):
            return ct >= tt
        return ct <= tt
