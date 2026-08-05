"""Manager market-context provider (Phase 8E-R / G2) — READ-ONLY normalization.

Delivers, per open position, the deterministic market context the accepted
PositionManager needs for structure trailing and max-duration:

  * current market price (broker truth is supplied separately by the service),
  * confirmed strategy swing + a stable structure_reference (from the engine's OWN
    ``confirmed_pivots`` — no pivot/trend recomputation),
  * bars_since_swing (structure freshness),
  * bars_open (completed exec bars since the verified broker open time),
  * source timeframe / latest-closed-bar timestamp / snapshot id / freshness.

It computes NO strategy signal and NO stop math. It owns only the normalization
and delivery of context; the PositionManager owns the trailing / max-duration
decision. Fails closed: missing / malformed / future / stale bars, or missing /
conflicting open-time evidence, yield no structure and no bars_open (the PM then
emits PM_TRAIL_PENDING / PM_DATA_STALE / holds max-duration). No networking.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..bridge import serialize
from ..live.providers import SymbolMap
from ..producer import providers
from ..producer.strategy_adapter import confirmed_structure


class ManagerMarketContextProvider:
    def __init__(self, market_provider, engine_module, *, symbol_map=None,
                 exec_timeframe="M15", pivot_k=1, max_context_age_sec=120,
                 continuity_bars=8, min_history_bars=3):
        self.market = market_provider
        self.module = engine_module
        self.map = symbol_map or SymbolMap()
        self.exec_timeframe = exec_timeframe
        self.pivot_k = int(pivot_k)
        self.max_context_age_sec = max_context_age_sec
        self.continuity_bars = continuity_bars
        self.min_history_bars = min_history_bars

    def context(self, broker_symbol, direction, now, opened_epoch):
        """Deterministic per-position context. ``broker_symbol`` is the terminal
        symbol; ``opened_epoch`` is the broker position open time (epoch seconds),
        the single source of position-open evidence for bars_open."""
        base = {
            "symbol": broker_symbol, "direction": direction,
            "source_timeframe": self.exec_timeframe,
            "generated_at": serialize.iso_utc(now),
            "max_age_sec": self.max_context_age_sec,
            "market_price": None, "confirmed_swing": None,
            "structure_reference": None, "bars_since_swing": None,
            "bars_open": None, "latest_closed_bar_timestamp": None,
            "source_snapshot_id": None, "fresh": False, "reason": None,
        }
        canonical = self.map.to_canonical(broker_symbol)
        bars = self.market.get_bars(canonical, self.exec_timeframe, now)
        # closed-bars-only, no-future, freshness + continuity via the ACCEPTED
        # validator (fail closed on missing/stale/gapped/unclosed/future).
        ok, reason = providers.validate_bars(
            bars, self.exec_timeframe, now, self.max_context_age_sec,
            self.continuity_bars, self.min_history_bars)
        if not ok:
            base["reason"] = reason
            return base                                    # fail closed
        base["fresh"] = True
        base["source_snapshot_id"] = bars.version()
        base["latest_closed_bar_timestamp"] = serialize.iso_utc(bars.last["open_time"])
        base["market_price"] = float(bars.last["close"])
        # structure: engine's own confirmed_pivots (no recomputation, no future bar)
        struct = confirmed_structure(self.module, bars, direction, self.pivot_k)
        if struct is not None:
            base["confirmed_swing"] = struct["price"]
            base["structure_reference"] = struct["structure_reference"]
            base["bars_since_swing"] = struct["bars_since_swing"]
        # max-duration: completed exec bars since the verified broker open time
        base["bars_open"] = self._bars_open(bars, opened_epoch)
        return base

    def _bars_open(self, bars, opened_epoch):
        """Count CLOSED exec bars that opened strictly after the position's broker
        open time. Uses real bars, so weekend/holiday gaps do not inflate the count.
        None (fail closed) on missing / malformed open-time evidence."""
        if opened_epoch is None:
            return None
        try:
            opened = datetime.fromtimestamp(int(opened_epoch), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return None
        return sum(1 for r in bars.rows if r["open_time"] > opened)
