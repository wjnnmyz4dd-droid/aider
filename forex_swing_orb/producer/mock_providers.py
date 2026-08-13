"""Deterministic in-memory providers + a stub engine (TEST/DEV ONLY, Phase 7A).

These are test doubles — never shipped as live providers. No networking. They let
the runner orchestration be exercised deterministically alongside the existing
mock MT5 / bridge harness. Live MT5-backed providers are a later phase.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from ..bridge import serialize
from .contract import tf_minutes
from .providers import (AccountStateProvider, Bars, BrokerHealthProvider,
                        MarketDataProvider, NewsDataProvider)
from .scheduler import last_closed_open


def make_bars(symbol, tf, now, n=80, base=1.10000):
    """n contiguous CLOSED bars ending at the schedule's latest closed bar."""
    m = tf_minutes(tf)
    last_open = last_closed_open(now, tf)
    rows = []
    for i in range(n - 1, -1, -1):
        ot = last_open - timedelta(minutes=m * i)
        px = base + 0.0001 * ((n - i) % 5)
        rows.append({"open_time": ot, "open": px, "high": px + 0.0002,
                     "low": px - 0.0002, "close": px + 0.0001})
    return Bars(symbol, tf, rows)


class MockMarketDataProvider(MarketDataProvider):
    def __init__(self, symbols, now, history=120):
        self._overrides = {}
        self._symbols = tuple(symbols)
        self._now = now
        self._history = history

    def set(self, symbol, tf, bars):
        self._overrides[(symbol, tf)] = bars

    def get_bars(self, symbol, tf, now):
        if (symbol, tf) in self._overrides:
            return self._overrides[(symbol, tf)]
        if symbol not in self._symbols:
            return None
        n = self._history if tf == "M15" else 10
        return make_bars(symbol, tf, now, n=n)


class MockAccountProvider(AccountStateProvider):
    def __init__(self, now, **over):
        self._snap = {
            "balance": 100000.0, "current_balance": 100000.0, "equity": 100000.0,
            "initial_balance": 100000.0, "day_start_balance": 100000.0,
            "day_start_equity": 100000.0,          # H2/P3A-3: complete anchor
            "floating_pl": 0.0, "swaps": 0.0, "commissions": 0.0,
            "trading_day": None, "open_position_count": 0, "open_symbols": (),
            "terminal_connected": True, "as_of": serialize.iso_utc(now),
            "is_demo": True, "account_type": "DEMO",
        }
        self._snap.update(over)

    def set(self, **over):
        self._snap.update(over)

    def snapshot(self, now):
        if self._snap is None:
            return None
        return dict(self._snap)


class MockNewsProvider(NewsDataProvider):
    def __init__(self, now, events=None, verified=True, as_of=None):
        self._bundle = {"as_of": as_of or serialize.iso_utc(now),
                        "verified": verified, "events": events or []}

    def set_bundle(self, bundle):
        self._bundle = bundle

    def bundle(self, now):
        return self._bundle


class MockBrokerHealthProvider(BrokerHealthProvider):
    def __init__(self, **over):
        self._snap = {
            "terminal_connected": True, "bridge_healthy": True,
            "spread_points": 5.0, "max_spread_points": 20.0,
            "recent_slippage_points": 1.0, "max_slippage_points": 10.0,
            "missing_ack_count": 0, "quote_age_sec": 1.0, "max_quote_age_sec": 30.0,
            "symbol_tradable": True, "market_open": True,
            # M9: symbol tick/volume metadata for authoritative sizing (EURUSD-like
            # 5-digit defaults; tick_value is account-currency-denominated).
            "tick_size": 0.00001, "tick_value": 1.0,
            "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
        }
        self._snap.update(over)

    def set(self, **over):
        self._snap.update(over)

    def snapshot(self, symbol, now):
        return dict(self._snap)


class StubEngine:
    """A SignalEngine-shaped test double: emits a controlled instruction for the
    last exec bar (or none). It stands in for the frozen engine so runner
    orchestration is deterministic without crafting signal-triggering OHLC."""

    def __init__(self, emit=True, direction="LONG", risk_fraction=0.0025,
                 entry=1.10000, session_id="LONDON"):
        self.emit = emit
        self.direction = direction
        self.risk_fraction = risk_fraction
        self.entry = entry
        self.session_id = session_id
        self.instructions = {}
        self.audit = {}

    def generate(self, data_map):
        self.instructions = {}
        for sym, df in data_map.items():
            if not self.emit:
                self.instructions[sym] = []
                continue
            gen = serialize.iso_utc(df.index[-1].to_pydatetime())
            entry = self.entry
            if self.direction == "LONG":
                stop, target = entry - 0.0020, entry + 0.0040
            else:
                stop, target = entry + 0.0020, entry - 0.0040
            session_id = getattr(self, "session_id", "LONDON")
            sid = hashlib.sha256(
                f"{sym}|{session_id}|{self.direction}|{gen}|{entry}|{stop}|{target}".encode()
            ).hexdigest()[:16]
            self.instructions[sym] = [{
                "schema_version": 2, "signal_id": sid, "session_id": session_id,
                "strategy_id": "forex_swing_orb",
                "strategy_version": "swing_orb.v1.4.0",
                "symbol": sym, "direction": self.direction,
                "entry_price": round(entry, 5), "stop_loss": round(stop, 5),
                "take_profit": round(target, 5), "risk_fraction": self.risk_fraction,
                "generated_timestamp": gen,
                "expiration_timestamp": serialize.iso_utc(
                    (df.index[-1] + timedelta(minutes=30)).to_pydatetime()),
                "evidence_summary": {"trend_d1": "BULLISH", "trend_h4": "BULLISH"},
                "news_eligibility": {"mode": "VERIFIED", "active": True},
            }]
        return {s: None for s in data_map}
