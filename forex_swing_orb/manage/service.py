"""Manager service (Phase 7B-B) — demo-only stop-management loop, sibling to the
producer. Runs the accepted PositionManager via the BridgeMt5Adapter, enforces
one-in-flight, reconciles, and exposes read-only status. No console required.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
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

    def register(self, signal_id, ticket, symbol, direction, entry, initial_stop,
                 take_profit, now):
        return self.pm.register(signal_id, ticket, symbol, direction, entry,
                                initial_stop, take_profit, now)

    def run_cycle(self, now, *, market=None, structures=None, bars_since=None,
                  bars_open=None, kill_switch=None):
        market = market or {}
        structures = structures or {}
        bars_since = bars_since or {}
        bars_open = bars_open or {}
        ks = self._kill(now) if kill_switch is None else kill_switch
        results = []
        for sid in list(self.pm.states.keys()):
            st = self.pm.states[sid]
            ticket = st["ticket"]
            # provide broker-constraint context to the adapter (additive state keys)
            st["_market_reference"] = market.get(ticket)
            st["_broker_min_stop_distance"] = 0.0
            # one-in-flight: try to resolve a persisted in-flight, else reconcile
            if self.ledger.get_inflight(ticket) is not None:
                self.adapter.reconcile_inflight(ticket)
                if self.ledger.get_inflight(ticket) is not None:
                    results.append(self.pm.recover(sid, now))
                    continue
            rec = self.pm.evaluate(
                sid, market_price=market.get(ticket), now=now, kill_switch=ks,
                structure_reference=structures.get(ticket),
                bars_since_swing=bars_since.get(ticket), bars_open=bars_open.get(ticket))
            results.append(rec)
        if self.health_path is not None:
            self._write_health(now)
        return results

    def status(self, now):
        inflight = dict(self.ledger.inflight)
        return {
            "service_state": "READY",
            "terminal_connected": self._safe_connected(),
            "tracked_tickets": len(self.pm.states),
            "in_flight_count": len(inflight),
            "in_flight": inflight,
            "unresolved_reconciliation_count": len(inflight),
            "tracked_signals": list(self.pm.states.keys()),
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

    # -- Phase 8D: autonomous demo wiring ----------------------------------
    def discover_and_register(self, now):
        """Adopt open broker positions carrying a known ENTER signal_id into the
        PositionManager, recovering their approved initial reference from the ENTER
        bridge (fail closed per position). Read-only discovery; registers nothing it
        cannot anchor to an approved trade. Returns the list of registrations made."""
        from ..runtime import adoption
        truth = getattr(self, "_truth", None)
        enter_paths = getattr(self, "_enter_paths", None)
        if truth is None or enter_paths is None:
            return []
        regs = adoption.discover_registrations(truth, enter_paths, self.pm.states.keys())
        for r in regs:
            self.register(r["signal_id"], r["ticket"], r["symbol"], r["direction"],
                          r["entry"], r["initial_stop"], r["take_profit"], now)
        return regs

    def run_once(self, now):
        """One autonomous demo cycle: adopt new positions, then evaluate all tracked
        tickets against current broker prices (read via the truth source). Structure/
        bar context is not fed here (the manager never fabricates it), so structure-
        based trailing simply does not trigger; price/kill/weekend/duration logic and
        reconciliation run normally."""
        from ..runtime import adoption
        self.discover_and_register(now)
        truth = getattr(self, "_truth", None)
        market = adoption.market_from_truth(truth) if truth is not None else {}
        return self.run_cycle(now, market=market)

    @classmethod
    def build_from_env(cls, env=None, config_path=None, client=None, now_fn=None):
        """Construct a fully-wired, DEMO-ONLY ManagerService from validated config
        and the live MT5-backed broker-truth source. Fails closed on any missing /
        invalid configuration or an unusable FTMO profile. ``client`` is injected
        only by integration tests (a ``FakeMt5Client``); production creates it from
        config via the live MT5 client factory.
        """
        from datetime import datetime, timezone

        from ..bridge.paths import BridgePaths
        from ..ea_mt5.position_manager import PositionManager
        from ..runtime import wiring
        from ..runtime.config import load_config
        from .adapter import BridgeMt5Adapter
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
        return service
