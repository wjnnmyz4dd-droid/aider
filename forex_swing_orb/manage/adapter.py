"""BridgeMt5Adapter (Phase 7B-B) — bounded-wait bridge-backed mt5 interface.

Implements exactly the narrow ``mt5`` interface the accepted PositionManager
depends on (``terminal_connected/position_by_ticket/symbol_info`` = read broker
truth; ``modify_stop/position_close`` = route through the manage bridge and wait,
bounded, for the MANAGE_RESULT). No PM arithmetic changes; the PM's synchronous
verify is satisfied because on APPLIED the read-back reflects broker truth.
"""

from __future__ import annotations

from ..bridge import serialize
from ..ea_mt5 import mock_mt5 as mt5c
from . import contract as MC
from . import paths as P
from . import ticks
from .ledger import ManageLedger
from .producer import write_manage_instruction

# result status -> PM-visible retcode mapping
_DONE = mt5c.TRADE_RETCODE_DONE
_CONSTRAINT = mt5c.TRADE_RETCODE_INVALID_STOPS
_UNCERTAIN = mt5c.TRADE_RETCODE_CONNECTION


class _Res:
    def __init__(self, retcode, position=0):
        self.retcode = retcode
        self.position = position

    @property
    def ok(self):
        return self.retcode == _DONE


class BridgeMt5Adapter:
    def __init__(self, truth, mpaths, *, ledger=None, audit=None, now_fn=None,
                 timeout_sec=30.0, poll_interval_sec=0.5, sleep_fn=None, pump=None,
                 ttl_sec=120, source_component=MC.SOURCE_COMPONENT):
        self.truth = truth                      # read-only broker-truth source (mock/live)
        self.paths = mpaths if isinstance(mpaths, P.ManagePaths) else P.ManagePaths(mpaths)
        self.ledger = ledger or ManageLedger(self.paths.ledger)
        self.audit = audit
        self.pm = None                          # bound by the manager
        self._now_fn = now_fn
        self.timeout_sec = timeout_sec
        self.poll_interval_sec = poll_interval_sec
        self._sleep = sleep_fn or __import__("time").sleep
        self._pump = pump                       # test seam: drive the consumer between polls
        self.ttl_sec = ttl_sec
        self.source_component = source_component

    def bind(self, pm):
        self.pm = pm
        return self

    # -- read-only broker-truth delegation ---------------------------------
    def terminal_connected(self):
        return self.truth.terminal_connected()

    def position_by_ticket(self, ticket):
        return self.truth.position_by_ticket(ticket)

    def deals_for_position(self, position_id):
        # H1: read-only pass-through so the PM can positively confirm a close from
        # deal history. Absent capability -> None (never inferred as closed).
        getter = getattr(self.truth, "deals_for_position", None)
        return getter(position_id) if getter is not None else None

    def symbol_info(self, symbol):
        return self.truth.symbol_info(symbol)

    # -- write path: modify_stop -------------------------------------------
    def modify_stop(self, ticket, sl):
        return self._emit_and_wait(ticket, MC.ManageAction.MODIFY_STOP, sl)

    def position_close(self, ticket, reason=None):
        # R3: carry the specific frozen PMReason (kill/weekend/max-duration) so the
        # EA can independently authorize the close. None -> unauthorized (fail closed).
        return self._emit_and_wait(ticket, MC.ManageAction.PROTECTIVE_CLOSE, None, reason=reason)

    # -- core bounded-wait --------------------------------------------------
    def _emit_and_wait(self, ticket, action, sl, reason=None):
        now = self._now_fn()
        st = self._ctx(ticket)
        if st is None:
            return _Res(_UNCERTAIN, ticket)         # unknown ticket -> PM reconciles
        sym = st["symbol"]

        # R2: resolve any existing in-flight BEFORE allocating a sequence or emitting.
        # Never allocate a seq or write a second instruction while one is unresolved;
        # timeout leaves in-flight set, so the next call defers (no duplicate emit).
        if self.ledger.get_inflight(ticket) is not None:
            self.reconcile_inflight(ticket)         # clear iff a terminal result arrived
            if self.ledger.get_inflight(ticket) is not None:
                return _Res(_UNCERTAIN, ticket)     # still in-flight -> PM reconciles this cycle

        seq = self.ledger.next_seq(ticket)
        pm_reason = (f"PM_MODIFY@{st['phase']}" if action == MC.ManageAction.MODIFY_STOP
                     else (reason if reason else "PM_UNAUTHORIZED_CLOSE"))
        fields = {
            "signal_id": st["signal_id"], "ticket": ticket, "symbol": sym,
            "direction": st["direction"], "action": action,
            # M11/PR-3L: transport the PM-authorized stop VERBATIM — the PM already
            # quantized it on the authoritative H6 grid and fails closed when geometry
            # is unknown, so the transport must not re-quantize onto a (possibly
            # guessed) grid. point/digits below are authoritative-sourced metadata only.
            "target_stop": sl,
            "expected_current_stop": (st["current_stop"] if action == MC.ManageAction.MODIFY_STOP else None),
            "prior_stop": st["current_stop"], "pm_phase": st["phase"],
            "pm_reason": pm_reason,
            "structure_reference": st.get("last_structure_ref"),
            "market_reference": st.get("_market_reference"),
            "point": ticks.point(self.truth, sym), "digits": ticks.digits(self.truth, sym),
            "broker_min_stop_distance": st.get("_broker_min_stop_distance", 0.0),
            "per_ticket_sequence": seq,
            "generated_timestamp": serialize.iso_utc(now),
            "expiration_timestamp": serialize.iso_utc(self._plus(now, self.ttl_sec)),
            "source_component": self.source_component,
            "initial_r_digest": MC.initial_r_digest(st["direction"], st["entry"], st["initial_stop"]),
        }
        instr = MC.build_instruction(fields)
        mid = instr["manage_id"]

        # idempotent: already terminal from a prior attempt (same manage_id)
        if self.ledger.is_terminal(mid):
            return self._map_status(self.ledger.terminal_status(mid), ticket)

        self.ledger.set_inflight(ticket, mid)
        write_manage_instruction(self.paths, instr, now, audit=self.audit)

        deadline = self.timeout_sec
        waited = 0.0
        while True:
            if self._pump is not None:
                self._pump(now)                      # drive the (separate) EA consumer in tests
            res = self._find_result(mid)
            if res is not None:
                status = res["status"]
                if status not in MC.ManageStatus.NON_TERMINAL:
                    self.ledger.record_terminal(mid, ticket, status, seq)  # clears in-flight
                return self._map_status(status, ticket)
            if waited >= deadline:
                return _Res(_UNCERTAIN, ticket)      # timeout -> PM reconciliation; in-flight persists
            self._sleep(self.poll_interval_sec)
            waited += self.poll_interval_sec

    def reconcile_inflight(self, ticket):
        """Resolve a persisted in-flight entry. Returns the terminal status if one
        converged, else None. Two convergent paths:

        1. A terminal result has arrived (the uncertain->converged path): record
           it (which clears in-flight).
        2. M-5 proven orphan: the in-flight marker persisted but its manage_id
           exists NOWHERE durable in the bridge (crash between ``set_inflight`` and
           the atomic ``write_manage_instruction``). Nothing reached the EA/broker,
           so the instruction never happened — clearing is duplicate-safe and lets
           the PositionManager re-decide fresh through the normal broker-verified
           emit path. Conservative: only clear on POSITIVE proof of absence
           everywhere (``_bridge_has`` fails closed on any read error), never on
           mere elapsed time and never while any instruction/result exists."""
        mid = self.ledger.get_inflight(ticket)
        if mid is None:
            return None
        res = self._find_result(mid)
        if res is not None and res["status"] not in MC.ManageStatus.NON_TERMINAL:
            self.ledger.record_terminal(mid, ticket, res["status"],
                                        self.ledger.seq.get(str(ticket), 0))
            return res["status"]
        if res is None and not self._bridge_has(mid):
            self.ledger.clear_inflight(ticket)       # proven orphan -> self-heal
            self._audit_orphan(mid, ticket)
        return None

    def recover_orphans(self, now=None):
        """Startup/cycle sweep: reconcile every persisted in-flight entry so a
        crash orphan is healed at the top of the autonomous cycle. A proven orphan
        is cleared; a genuine in-flight (instruction present / result pending) is
        left untouched for the normal reconcile/recover path. Returns the list of
        tickets whose in-flight was cleared this sweep (observational)."""
        cleared = []
        for tkey in list(self.ledger.inflight.keys()):
            if self.ledger.inflight.get(tkey) is None:
                continue
            self.reconcile_inflight(tkey)
            if self.ledger.get_inflight(tkey) is None:
                cleared.append(tkey)
        return cleared

    # -- helpers ------------------------------------------------------------
    def _bridge_has(self, manage_id):
        """True iff ``manage_id`` appears in ANY durable bridge location: a pending
        or claimed instruction, an archived instruction (applied/rejected/closed),
        a quarantined instruction, or a result file. Absence everywhere proves the
        instruction was never written (an M-5 orphan). Any OS error -> True (fail
        closed: an unreadable bridge is never treated as proof of absence)."""
        name = P.instruction_name(manage_id)
        try:
            for d in (self.paths.pending, self.paths.claimed,
                      self.paths.archive_applied, self.paths.archive_rejected,
                      self.paths.archive_closed, self.paths.quarantine):
                if (d / name).exists():
                    return True
            if self.paths.results.exists():
                for _ in self.paths.results.glob(f"{manage_id}.*.json"):
                    return True
            return False
        except OSError:
            return True

    def _audit_orphan(self, manage_id, ticket):
        """Observational-only diagnostic recording that a proven-orphan in-flight
        marker was cleared. Best-effort: observability must NEVER break the
        management path, so every failure is swallowed."""
        from ..bridge.atomic import append_line_fsync
        try:
            now = self._now_fn() if self._now_fn is not None else None
            rec = {"kind": "manage_orphan_cleared", "manage_id": manage_id,
                   "ticket": str(ticket), "outcome": "INFLIGHT_ORPHAN_CLEARED",
                   "timestamp": serialize.iso_utc(now) if now is not None else None,
                   "note": ("no durable instruction or result found for a persisted "
                            "in-flight marker; cleared for fresh PM re-decision")}
            append_line_fsync(self.paths.audit_log, serialize.canonical_json(rec))
        except Exception:
            pass

    def _map_status(self, status, ticket):
        S = MC.ManageStatus
        if status in (S.APPLIED, S.ALREADY_APPLIED, S.NO_OP_CLOSED):
            return _Res(_DONE, ticket)
        if status in (S.REJECTED_BROKER_CONSTRAINT, S.REJECTED_INVALID, S.BROKER_REJECTED):
            return _Res(_CONSTRAINT, ticket)
        return _Res(_UNCERTAIN, ticket)              # stale/loosen/no_position/uncertain -> reconcile

    def _find_result(self, manage_id):
        if not self.paths.results.exists():
            return None
        for f in self.paths.results.glob(f"{manage_id}.*.json"):
            ok, rec = serialize.loads(f.read_text(encoding="utf-8"))
            if ok and rec.get("manage_id") == manage_id and serialize.verify_integrity_digest(rec):
                return rec
        return None

    def _ctx(self, ticket):
        if self.pm is None:
            return None
        sid = self.pm._ticket_owner.get(ticket)
        if sid is None:
            return None
        return self.pm.states.get(sid)

    def _plus(self, now, secs):
        from datetime import timedelta
        return now + timedelta(seconds=secs)
