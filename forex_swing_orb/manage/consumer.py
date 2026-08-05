"""Manage handler — EA-side reference (Phase 7B-B).

This is the Python reference/specification the MQL5 manage handler mirrors 1:1
(exactly as ``execution_consumer.py`` is the reference for the entry EA). It is
the ONE manage applier: claim -> 18-step bounded-authority validation -> apply ->
broker read-back verify -> terminal result -> archive. It never opens a trade,
never reverses direction, never changes TP, never loosens/removes a stop. Uses
the frozen never-loosen invariant (``position.contract.stop_move_is_legal``).
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from ..ea_mt5 import mock_mt5 as mt5c
from ..position.contract import stop_move_is_legal, DEFAULT_PM_CONFIG
from . import contract as MC
from . import paths as P
from . import ticks
from .ledger import ManageLedger

_BUY, _SELL = mt5c.ORDER_TYPE_BUY, mt5c.ORDER_TYPE_SELL


def _dir(pos):
    return "LONG" if pos.type == _BUY else "SHORT"


class ManageConsumer:
    def __init__(self, mt5, mpaths, ledger=None, audit=None, cfg=DEFAULT_PM_CONFIG):
        self.mt5 = mt5
        self.paths = mpaths if isinstance(mpaths, P.ManagePaths) else P.ManagePaths(mpaths)
        self.ledger = ledger or ManageLedger(self.paths.ea_ledger)   # EA's own dedup
        self.audit = audit
        self.cfg = cfg

    # -- claim (exclusive rename) ------------------------------------------
    def claim_next(self, now):
        if not self.paths.pending.exists():
            return None
        for f in sorted(self.paths.pending.glob("*.json")):
            mid = P.manage_id_from_name(f.name)
            if mid is None:
                f.replace(self.paths.quarantine / f.name)
                continue
            dst = self.paths.claimed / f.name
            try:
                f.rename(dst)          # atomic exclusive claim (no overwrite on POSIX)
            except OSError:
                continue
            return mid
        return None

    def run_once(self, now):
        mid = self.claim_next(now)
        if mid is None:
            return None
        return self.process(mid, now)

    # -- process one claimed instruction (18-step) -------------------------
    def process(self, manage_id, now):
        path = self.paths.claimed / P.instruction_name(manage_id)
        try:
            ok, rec = serialize.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not ok:
            return self._finalize(rec or {}, manage_id, MC.ManageStatus.QUARANTINED,
                                  "serde", now, path, quarantine=True)

        # 1 filename/manage_id, 2/3/4 schema/digest/fields
        if rec.get("manage_id") != manage_id:
            return self._finalize(rec, manage_id, MC.ManageStatus.QUARANTINED, "id_mismatch",
                                  now, path, quarantine=True)
        vok, vreason = MC.validate_instruction(rec)
        if not vok:
            st = (MC.ManageStatus.REJECTED_EXPIRED if vreason == "expiration"
                  else MC.ManageStatus.REJECTED_INVALID)
            return self._finalize(rec, manage_id, st, vreason, now, path)

        ticket = rec["ticket"]
        sym = rec["symbol"]
        seq = int(rec["per_ticket_sequence"])

        # 9 dedup / terminal evidence (idempotent). Filesystem is the durable
        # truth (survives ledger loss): a prior result/archive => already terminal.
        if self.ledger.is_terminal(manage_id) or self._fs_terminal(manage_id):
            prev = self.ledger.terminal_status(manage_id) or "fs"
            # idempotent: the ORIGINAL terminal result stands (exactly one per
            # manage_id). Archive the duplicate claimed file; write no 2nd result.
            return self._finalize(rec, manage_id, MC.ManageStatus.ALREADY_APPLIED,
                                  f"dedup:{prev}", now, path, archive="applied",
                                  write_result=False)
        # 8 sequence: older-than-terminal rejected; same-seq/other-id conflict quarantines
        last_term = self.ledger.last_terminal_seq(ticket)
        if seq < last_term:
            return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_STALE,
                                  "old_sequence", now, path)
        for oid, orec in self.ledger.terminal.items():
            if str(orec.get("ticket")) == str(ticket) and int(orec.get("sequence", -1)) == seq and oid != manage_id:
                return self._finalize(rec, manage_id, MC.ManageStatus.QUARANTINED,
                                      "sequence_conflict", now, path, quarantine=True)

        # 5 expiry
        if serialize.parse_iso(rec["expiration_timestamp"]) <= now:
            return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_EXPIRED,
                                  "expired", now, path)

        # 14 terminal connectivity (checked early to avoid partial apply)
        try:
            if not self.mt5.terminal_connected():
                return self._nonterminal(rec, manage_id, MC.ManageStatus.TERMINAL_DISCONNECTED,
                                         now, path)
            pos = self.mt5.position_by_ticket(ticket)
        except mt5c.MT5Disconnected:
            return self._nonterminal(rec, manage_id, MC.ManageStatus.TERMINAL_DISCONNECTED,
                                     now, path)

        # 7 position exists/open, 4-closed
        if pos is None:
            st = (MC.ManageStatus.NO_OP_CLOSED if rec["action"] == MC.ManageAction.PROTECTIVE_CLOSE
                  else MC.ManageStatus.NO_POSITION)
            return self._finalize(rec, manage_id, st, "no_position", now, path,
                                  archive="closed")
        # 6 symbol/direction match
        if pos.symbol != sym or _dir(pos) != rec["direction"]:
            return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_INVALID,
                                  "identity_mismatch", now, path)

        observed_before = pos.sl

        if rec["action"] == MC.ManageAction.PROTECTIVE_CLOSE:
            # R3: independently authorize the close against the frozen reason set.
            if not MC.protective_close_authorized(rec.get("pm_reason")):
                return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_INVALID,
                                      "unauthorized_close", now, path,
                                      observed_before=observed_before)
            return self._apply_close(rec, manage_id, pos, observed_before, now, path)

        # ---- MODIFY_STOP path ----
        target = rec["target_stop"]
        expected = rec["expected_current_stop"]
        # 10 compare-and-swap (against LIVE broker stop)
        if not ticks.eq_stop(observed_before, expected, self.mt5, sym):
            return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_STALE,
                                  "cas_mismatch", now, path, observed_before=observed_before)
        # 11 tick normalization
        qtarget = ticks.quantize(target, self.mt5, sym)
        # 12 risk-reducing-only (frozen never-loosen invariant)
        if not stop_move_is_legal(rec["direction"], observed_before, qtarget):
            return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_LOOSEN,
                                  "not_risk_reducing", now, path, observed_before=observed_before)
        # 13 broker min-stop / freeze distance vs reference price
        mref = rec.get("market_reference")
        mind = rec.get("broker_min_stop_distance") or 0.0
        if mref is not None and mind and abs(qtarget - float(mref)) < float(mind):
            return self._finalize(rec, manage_id, MC.ManageStatus.REJECTED_BROKER_CONSTRAINT,
                                  "min_stop", now, path, observed_before=observed_before)
        # 15 apply
        try:
            res = self.mt5.modify_stop(ticket, qtarget)
        except mt5c.MT5Disconnected:
            return self._nonterminal(rec, manage_id, MC.ManageStatus.TERMINAL_DISCONNECTED,
                                     now, path)
        if res.retcode != mt5c.TRADE_RETCODE_DONE:
            st = (MC.ManageStatus.REJECTED_BROKER_CONSTRAINT
                  if res.retcode in (mt5c.TRADE_RETCODE_INVALID_STOPS, mt5c.TRADE_RETCODE_REJECT)
                  else MC.ManageStatus.BROKER_REJECTED)
            return self._finalize(rec, manage_id, st, f"broker:{res.retcode}", now, path,
                                  observed_before=observed_before, broker_retcode=res.retcode)
        # 16 broker read-back verify
        try:
            pos2 = self.mt5.position_by_ticket(ticket)
        except mt5c.MT5Disconnected:
            return self._nonterminal(rec, manage_id, MC.ManageStatus.UNCERTAIN, now, path)
        if pos2 is None or not ticks.eq_stop(pos2.sl, qtarget, self.mt5, sym):
            return self._nonterminal(rec, manage_id, MC.ManageStatus.UNCERTAIN, now, path,
                                     observed_before=observed_before)
        return self._finalize(rec, manage_id, MC.ManageStatus.APPLIED, "ok", now, path,
                              observed_before=observed_before, observed_after=pos2.sl,
                              broker_retcode=res.retcode, archive="applied")

    def _apply_close(self, rec, manage_id, pos, observed_before, now, path):
        try:
            res = self.mt5.position_close(rec["ticket"])
        except mt5c.MT5Disconnected:
            return self._nonterminal(rec, manage_id, MC.ManageStatus.TERMINAL_DISCONNECTED,
                                     now, path)
        if res.retcode != mt5c.TRADE_RETCODE_DONE:
            return self._finalize(rec, manage_id, MC.ManageStatus.BROKER_REJECTED,
                                  f"broker:{res.retcode}", now, path, broker_retcode=res.retcode)
        return self._finalize(rec, manage_id, MC.ManageStatus.NO_OP_CLOSED, "closed", now, path,
                              observed_before=observed_before, archive="closed",
                              broker_retcode=res.retcode)

    # -- durable dedup evidence (filesystem is the source of truth) ---------
    def _fs_terminal(self, manage_id):
        """True iff a terminal result/archive artifact already exists for this
        manage_id (survives EA-ledger loss; prevents replay of a completed action)."""
        for d in (self.paths.archive_applied, self.paths.archive_rejected,
                  self.paths.archive_closed):
            if (d / P.instruction_name(manage_id)).exists():
                return True
        if self.paths.results.exists():
            for _ in self.paths.results.glob(f"{manage_id}.*.json"):
                return True
        return False

    # -- crash recovery over claimed/ --------------------------------------
    def recover(self, now):
        if not self.paths.claimed.exists():
            return []
        out = []
        for f in sorted(self.paths.claimed.glob("*.json")):
            mid = P.manage_id_from_name(f.name)
            if mid is None:
                f.replace(self.paths.quarantine / f.name)
                continue
            ok, rec = serialize.loads(f.read_text(encoding="utf-8"))
            if not ok:
                out.append(self._finalize(rec or {}, mid, MC.ManageStatus.QUARANTINED,
                                          "serde", now, f, quarantine=True))
                continue
            # crash after broker apply, before result: broker already at target?
            if rec.get("action") == MC.ManageAction.MODIFY_STOP:
                try:
                    pos = self.mt5.position_by_ticket(rec["ticket"])
                except mt5c.MT5Disconnected:
                    pos = None
                if pos is not None and ticks.eq_stop(pos.sl, rec.get("target_stop"),
                                                     self.mt5, rec["symbol"]):
                    out.append(self._finalize(rec, mid, MC.ManageStatus.ALREADY_APPLIED,
                                              "recovered_applied", now, f,
                                              observed_after=pos.sl, archive="applied"))
                    continue
            out.append(self.process(mid, now))   # re-evaluate CAS/expiry/etc from scratch
        return out

    # -- terminal + non-terminal result writers ----------------------------
    def _result(self, rec, manage_id, status, reason, now, **kw):
        return MC.build_result({
            "manage_id": manage_id, "signal_id": rec.get("signal_id"),
            "ticket": rec.get("ticket"), "symbol": rec.get("symbol"),
            "action": rec.get("action"), "requested_stop": rec.get("target_stop"),
            "expected_current_stop": rec.get("expected_current_stop"),
            "observed_stop_before": kw.get("observed_before"),
            "observed_stop_after": kw.get("observed_after"),
            "per_ticket_sequence": rec.get("per_ticket_sequence"),
            "status": status, "reason_code": reason,
            "broker_retcode": kw.get("broker_retcode"), "broker_message": kw.get("msg"),
            "claimed_timestamp": serialize.iso_utc(now),
            "applied_timestamp": serialize.iso_utc(now) if status in MC.ManageStatus.APPLIED_FAMILY else None,
            "completed_timestamp": serialize.iso_utc(now),
            "reconciliation_state": ("RECONCILE" if status in MC.ManageStatus.NON_TERMINAL else "TERMINAL"),
        })

    def _write_result(self, res, now):
        rid = serialize.compute_integrity_digest(res)[:16]
        atomic_write_text(self.paths.results / P.result_name(res["manage_id"], rid),
                          serialize.dumps(res))
        if self.audit is not None:
            self.audit.emit({"kind": "manage_result", "timestamp": serialize.iso_utc(now),
                             "manage_id": res["manage_id"], "signal_id": res["signal_id"],
                             "ticket": res["ticket"], "per_ticket_sequence": res["per_ticket_sequence"],
                             "action": res["action"], "status": res["status"],
                             "reason_code": res["reason_code"], "broker_retcode": res["broker_retcode"],
                             "observed_stop_before": res["observed_stop_before"],
                             "observed_stop_after": res["observed_stop_after"],
                             "expected_current_stop": res["expected_current_stop"],
                             "target_stop": res["requested_stop"],
                             "reconciliation_state": res["reconciliation_state"],
                             "correlation_id": res["manage_id"]})
        return res

    def _finalize(self, rec, manage_id, status, reason, now, path, quarantine=False,
                  archive="rejected", write_result=True, **kw):
        res = self._result(rec, manage_id, status, reason, now, **kw)
        if write_result:
            self._write_result(res, now)         # exactly one terminal result per manage_id
        # archive the claimed/pending file to the terminal family
        dest_dir = {"applied": self.paths.archive_applied, "closed": self.paths.archive_closed,
                    "rejected": self.paths.archive_rejected}[
            "applied" if status in MC.ManageStatus.APPLIED_FAMILY else
            "closed" if status in MC.ManageStatus.CLOSED_FAMILY else "rejected"]
        if quarantine:
            dest_dir = self.paths.quarantine
        try:
            if path.exists():
                path.replace(dest_dir / path.name)
        except OSError:
            pass
        self.ledger.record_terminal(manage_id, rec.get("ticket"), status,
                                    rec.get("per_ticket_sequence") or 0)
        return res

    def _nonterminal(self, rec, manage_id, status, now, path, **kw):
        """UNCERTAIN / TERMINAL_DISCONNECTED: no terminal result, leave the claimed
        file for recovery, do NOT record terminal, do NOT clear in-flight."""
        if self.audit is not None:
            self.audit.emit({"kind": "manage_nonterminal", "timestamp": serialize.iso_utc(now),
                             "manage_id": manage_id, "ticket": rec.get("ticket"),
                             "status": status, "reconciliation_state": "RECONCILE",
                             "correlation_id": manage_id})
        return self._result(rec, manage_id, status, "nonterminal", now, **kw)
