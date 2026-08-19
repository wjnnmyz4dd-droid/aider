"""Manager service (Phase 7B-B) — demo-only stop-management loop, sibling to the
producer. Runs the accepted PositionManager via the BridgeMt5Adapter, enforces
one-in-flight, reconciles, and exposes read-only status. No console required.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from ..position.contract import PMReason
from .ledger import ManageLedger


class ManagerService:
    def __init__(self, pm, adapter, mpaths, *, now_fn, health_path=None,
                 kill_switch=None):
        self.pm = pm
        self.adapter = adapter.bind(pm)
        self.paths = mpaths
        self.ledger = adapter.ledger if adapter.ledger is not None else ManageLedger(mpaths.ledger)
        self._now = now_fn
        self.health_path = health_path
        self._kill = kill_switch or (lambda now: False)
        self._last_error = None
        self._recovery_reconcile = set()   # sids whose restart recovery is unresolved
        self._context_provider = None      # G2: injected ManagerMarketContextProvider

    def register(self, signal_id, ticket, symbol, direction, entry, initial_stop,
                 take_profit, now):
        return self.pm.register(signal_id, ticket, symbol, direction, entry,
                                initial_stop, take_profit, now)

    def run_cycle(self, now, *, market=None, swings=None, structures=None,
                  bars_since=None, bars_open=None, kill_switch=None):
        market = market or {}
        swings = swings or {}
        structures = structures or {}
        bars_since = bars_since or {}
        bars_open = bars_open or {}
        ks = self._kill(now) if kill_switch is None else kill_switch
        results = []
        try:
            for sid in list(self.pm.states.keys()):
                # M2: fault isolation — one ticket's unexpected exception must not
                # starve the others. Each ticket is managed in its own boundary; a
                # failure records a diagnostic and leaves the position PROTECTED
                # (never marked CLOSED from an exception), then the cycle continues.
                try:
                    results.append(self._manage_one(sid, now, ks, market, swings,
                                                    structures, bars_since, bars_open))
                except Exception as exc:                    # narrow to per-ticket work
                    results.append(self._isolate_ticket_fault(sid, now, exc))
        finally:
            # cycle-level health must still be written even if a ticket faulted.
            if self.health_path is not None:
                try:
                    self._write_health(now)
                except Exception:
                    pass
        return results

    def _manage_one(self, sid, now, ks, market, swings, structures, bars_since, bars_open):
        st = self.pm.states[sid]
        ticket = st["ticket"]
        # provide broker-constraint context to the adapter (additive state keys)
        st["_market_reference"] = market.get(ticket)
        st["_broker_min_stop_distance"] = 0.0
        # one-in-flight: try to resolve a persisted in-flight, else reconcile
        if self.ledger.get_inflight(ticket) is not None:
            self.adapter.reconcile_inflight(ticket)
            if self.ledger.get_inflight(ticket) is not None:
                return self.pm.recover(sid, now)
        # one action per ticket per cycle: the PM makes the single decision from
        # the injected context (confirmed_swing + structure_reference enable
        # structure trailing; bars_open enables the max-duration decision).
        return self.pm.evaluate(
            sid, market_price=market.get(ticket), now=now, kill_switch=ks,
            confirmed_swing=swings.get(ticket),
            structure_reference=structures.get(ticket),
            bars_since_swing=bars_since.get(ticket), bars_open=bars_open.get(ticket))

    def _isolate_ticket_fault(self, sid, now, exc):
        """Record an isolated per-ticket management fault WITHOUT touching the
        position (it keeps its existing protective stop) and WITHOUT marking it
        CLOSED. Emits a fail-closed RECONCILIATION_REQUIRED audit line so the fault
        is observable and the ticket is re-examined next cycle."""
        st = self.pm.states.get(sid) or {}
        diag = {"stage": "manage_cycle", "error": type(exc).__name__,
                "reconciliation_status": "ticket_fault_isolated"}
        # emit the fail-closed PM audit line (best-effort); never touch the position.
        try:
            if st:
                self.pm._emit(st, PMReason.RECONCILIATION_REQUIRED, now,
                              reconciliation_status="ticket_fault_isolated")
        except Exception:
            pass
        return {"signal_id": sid, "reason_code": PMReason.RECONCILIATION_REQUIRED, **diag}

    def status(self, now):
        inflight = dict(self.ledger.inflight)
        recovery = sorted(self._recovery_reconcile)
        sess = None
        model = getattr(self, "_session_model", None)
        if model is not None:
            from ..session.model import session_snapshot
            sess = session_snapshot(model, now, getattr(self, "_capability", None))
        facts = {
            "terminal_connected": self._safe_connected(),
            "tracked_tickets": len(self.pm.states),
            "in_flight_count": len(inflight),
            "unresolved_reconciliation_count": len(inflight),
            "recovery_reconciliation_count": len(recovery),
            "last_error": self._last_error,
        }
        # Truthful manager state (no hard-coded READY): the single owner of the
        # manager health-vocabulary mapping is runtime.operator_status. IDLE and
        # MANAGING are healthy; ERROR/DISCONNECTED/RECONCILIATION_REQUIRED are not.
        from ..runtime import operator_status
        mstate = operator_status.manager_state(True, facts)
        return {
            "service_state": mstate["state"],
            "service_state_detail": mstate["detail"],
            "terminal_connected": facts["terminal_connected"],
            "tracked_tickets": facts["tracked_tickets"],
            "in_flight_count": facts["in_flight_count"],
            "in_flight": inflight,
            "unresolved_reconciliation_count": facts["unresolved_reconciliation_count"],
            "recovery_reconciliation_required": recovery,
            "recovery_reconciliation_count": facts["recovery_reconciliation_count"],
            "tracked_signals": list(self.pm.states.keys()),
            # Phase 9A: session context is for AUDIT/REPORTING only — protective
            # management (BE/lock/trail/authorized close) is NEVER blocked by session.
            "session": sess,
            "managing_outside_entry_session": bool(
                sess is not None and not sess["eligible"] and self.pm.states),
            "last_error": self._last_error,
            "timestamp": serialize.iso_utc(now),
        }

    def _safe_connected(self):
        try:
            return self.adapter.terminal_connected()
        except Exception:
            return None

    def _write_health(self, now):
        try:
            atomic_write_text(self.health_path, serialize.canonical_json(self.status(now)))
        except Exception as exc:
            self._last_error = repr(exc)

    # -- Phase 8D/8E-R (G4): restart-safe autonomous adoption --------------
    def discover_and_register(self, now):
        """Adopt open broker positions into the PositionManager, RESTART-SAFE.

        For each not-yet-tracked position with a valid signal_id comment:

          * prior PM audit history -> :meth:`PositionManager.recover` (the SOLE
            phase-recovery path: rebuilds the lifecycle phase from verified terminal
            outcomes + broker truth, adopts a tighter broker stop, never loosens,
            never guesses, and fails closed to PM_RECONCILIATION_REQUIRED on
            conflict);
          * manage-channel evidence but NO PM audit -> fail closed (corrupt history);
          * genuinely new (no PM/manage history) -> :meth:`register` at INITIAL from
            the approved ENTER immutable facts (skipped if unavailable — never
            guessed).

        Read-only discovery; emits no manage instruction. Returns per-position
        outcome dicts."""
        from ..runtime import adoption
        truth = getattr(self, "_truth", None)
        enter_paths = getattr(self, "_enter_paths", None)
        if truth is None or enter_paths is None:
            return []
        outcomes = []
        for pos in adoption.discover_positions(truth):
            sid, ticket = pos["signal_id"], pos["ticket"]
            if sid in self.pm.states:
                continue                          # idempotent: already adopted this session
            outcomes.append(self._adopt_one(sid, ticket, enter_paths, now))
        return outcomes

    def _adopt_one(self, sid, ticket, enter_paths, now):
        from ..position.contract import PMReason
        from ..runtime import adoption
        # 1. trustworthy prior PM history -> recover phase (fail closed on malformed)
        try:
            records = self.pm.audit.records_for(sid)
        except Exception:
            return self._recovery_reconciliation(sid, "malformed_pm_audit")
        if records:
            if adoption.audit_immutable_conflict(records):
                return self._recovery_reconciliation(sid, "conflicting_audit")
            if adoption.audit_ticket(records) != ticket:
                return self._recovery_reconciliation(sid, "ticket_mismatch")
            try:
                rec = self.pm.recover(sid, now)       # SOLE phase-recovery path
            except Exception:
                return self._recovery_reconciliation(sid, "recover_error")
            if rec is None:
                return self._recovery_reconciliation(sid, "recover_returned_none")
            # recover()'s return type varies (state vs audit record); the
            # authoritative outcome is the single audit record it just emitted.
            reason = self._last_pm_reason(sid)
            if reason in (PMReason.RECONCILIATION_REQUIRED, PMReason.DATA_STALE):
                self._recovery_reconcile.add(sid)     # tracked, but flagged unresolved
                return {"signal_id": sid, "mode": "recover",
                        "reason_code": reason, "reconciliation": True}
            self._recovery_reconcile.discard(sid)
            return {"signal_id": sid, "mode": "recover", "reason_code": reason}
        # 2. manage-channel evidence without PM audit -> corrupt/ambiguous history
        if self._manage_history(ticket):
            return self._recovery_reconciliation(sid, "manage_without_pm_audit")
        # 3. genuinely new position -> register at INITIAL from approved ENTER facts
        reg = adoption.enter_reference(enter_paths, sid, ticket)
        if reg is None or reg["ticket"] != ticket:
            return self._recovery_reconciliation(sid, "missing_immutable_entry")
        self.register(reg["signal_id"], reg["ticket"], reg["symbol"], reg["direction"],
                      reg["entry"], reg["initial_stop"], reg["take_profit"], now)
        self._recovery_reconcile.discard(sid)
        return {"signal_id": sid, "mode": "register"}

    def _last_pm_reason(self, sid):
        """The reason_code of the most recent PM audit record for ``sid`` (the one
        recover() just emitted), or None. Read-only."""
        try:
            recs = self.pm.audit.records_for(sid)
        except Exception:
            return None
        return recs[-1].get("reason_code") if recs else None

    def _manage_history(self, ticket):
        """True if the manage channel holds prior evidence for this ticket (an
        in-flight instruction or a terminal result). Unreadable ledger -> True
        (fail closed)."""
        try:
            if self.ledger.get_inflight(ticket) is not None:
                return True
            return self.ledger.last_terminal_seq(ticket) > 0
        except Exception:
            return True

    def _recovery_reconciliation(self, sid, why):
        """A restart position that cannot be safely recovered: adopt nothing, emit
        no modification, surface it as unresolved recovery (fail closed)."""
        self._recovery_reconcile.add(sid)
        return {"signal_id": sid, "mode": "reconciliation_required", "why": why}

    def run_once(self, now):
        """One autonomous demo cycle: adopt/recover positions, read broker truth,
        obtain deterministic market context (confirmed structure + bars_open) from
        the injected context provider, and evaluate each tracked ticket. Structure
        trailing and max-duration are now operational; the PM still makes the single
        decision per ticket. One-in-flight and restart rules are preserved."""
        from ..runtime import adoption
        self.discover_and_register(now)
        # M-5: heal any crash orphan (in-flight marker persisted before its
        # instruction was durably written) at the top of the cycle, so a stranded
        # ticket can be managed again this same cycle. Proven-orphan-only; never
        # clears a genuine in-flight (see BridgeMt5Adapter.recover_orphans).
        self.adapter.recover_orphans(now)
        truth = getattr(self, "_truth", None)
        if truth is None:
            return self.run_cycle(now)
        market = adoption.market_from_truth(truth)
        opens = adoption.open_times_from_truth(truth)
        swings, structures, bars_since, bars_open = self._market_context(now, opens)
        return self.run_cycle(now, market=market, swings=swings, structures=structures,
                              bars_since=bars_since, bars_open=bars_open)

    def reconcile_outcomes(self, now):
        """Read-only, NON-BLOCKING closed-trade outcome pass, run adjacent to the
        management cycle. Records normalized realized R for truly-closed positions.
        Any failure is swallowed here so outcome recording can NEVER delay or change
        trading behavior. Returns the list of newly-written outcomes (or [])."""
        reconciler = getattr(self, "_outcome_reconciler", None)
        if reconciler is None:
            return []
        try:
            return reconciler.run(now)
        except Exception as exc:                # never propagate into the trading loop
            self._last_error = repr(exc)
            return []

    def _market_context(self, now, opens):
        """Assemble per-ticket structure + bars_open from the injected context
        provider (read-only). Fail-closed contexts contribute nothing (the PM then
        holds trailing / max-duration). No structure or pivot logic lives here."""
        swings, structures, bars_since, bars_open = {}, {}, {}, {}
        ctxp = self._context_provider
        if ctxp is None:
            return swings, structures, bars_since, bars_open
        for sid, st in self.pm.states.items():
            ticket = st["ticket"]
            try:
                ctx = ctxp.context(st["symbol"], st["direction"], now, opens.get(ticket))
            except Exception as exc:                       # never crash the loop
                self._last_error = repr(exc)
                continue
            if not isinstance(ctx, dict):
                continue
            if ctx.get("confirmed_swing") is not None and ctx.get("structure_reference"):
                swings[ticket] = ctx["confirmed_swing"]
                structures[ticket] = ctx["structure_reference"]
                bars_since[ticket] = ctx["bars_since_swing"]
            if ctx.get("bars_open") is not None:
                bars_open[ticket] = ctx["bars_open"]
        return swings, structures, bars_since, bars_open

    @classmethod
    def build_from_env(cls, env=None, config_path=None, client=None, now_fn=None):
        """Construct a fully-wired, DEMO-ONLY ManagerService from validated config
        and the live MT5-backed broker-truth source. Fails closed on any missing /
        invalid configuration or an unusable FTMO profile. ``client`` is injected
        only by integration tests (a ``FakeMt5Client``); production creates it from
        config via the live MT5 client factory.
        """
        from datetime import datetime, timezone

        from pathlib import Path

        from ..agents.memory import MemoryStore
        from ..bridge.paths import BridgePaths
        from ..ea_mt5.position_manager import PositionManager
        from ..runtime import wiring
        from ..runtime.config import load_config
        from .adapter import BridgeMt5Adapter
        from .outcome import OutcomeReconciler
        from .paths import ManagePaths

        cfg = load_config(env=env, config_path=config_path)
        cfg.ensure_runtime_dir()
        wiring.build_compliance_config(cfg)          # fail closed if profile unusable

        if client is None:                            # pragma: no cover - real terminal
            client = wiring.build_client(cfg, env=env)
        if now_fn is None:
            now_fn = lambda: datetime.now(timezone.utc)   # noqa: E731

        truth = wiring.build_truth_source(client)
        mpaths = ManagePaths(cfg.bridge_root).ensure()
        adapter = BridgeMt5Adapter(truth, mpaths, now_fn=now_fn)
        pm = PositionManager(adapter, cfg.pm_audit_path)
        service = cls(pm, adapter, mpaths, now_fn=now_fn,
                      health_path=cfg.manager_health_path)
        service._truth = truth
        service._enter_paths = BridgePaths(cfg.bridge_root).ensure()
        service._cadence_sec = cfg.cadence_sec
        service._context_provider = wiring.build_context_provider(client, cfg)
        from ..session.capability import LONDON_ORB_CAPABILITY
        service._session_model = cfg.session_model()      # audit/reporting only
        service._capability = LONDON_ORB_CAPABILITY
        # PR-1: read-only, non-blocking closed-trade outcome edge. Reads broker
        # truth + PM audit history; writes only the shared MemoryStore. No trading.
        memory = MemoryStore(str(Path(cfg.runtime_dir) / "memory"))
        service._outcome_reconciler = OutcomeReconciler(
            truth, pm.audit, memory, now_fn=now_fn)
        return service
