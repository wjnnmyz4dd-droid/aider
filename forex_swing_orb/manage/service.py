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
