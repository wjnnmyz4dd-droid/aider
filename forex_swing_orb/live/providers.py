"""Live MT5-backed providers (Phase 8A) — READ-ONLY adapters.

They normalize live MT5 data into the accepted repository contracts and contain
NO trading logic: they never place trades, modify stops, generate signals,
compute strategy, or make compliance decisions. They fail closed on missing /
malformed / disconnected data. Forex-only. No HTTP / socket / scraping — the only
external integration is the injected MT5 client (see ``mt5_client``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..bridge import serialize
from ..compliance import mapping
from ..producer.providers import (AccountStateProvider, Bars, BrokerHealthProvider,
                                  MarketDataProvider, NewsDataProvider)
from . import mt5_client as mc


# --------------------------------------------------------------------------- #
# Canonical <-> broker symbol mapping (Forex-only)
# --------------------------------------------------------------------------- #
class SymbolMap:
    def __init__(self, suffix=""):
        self.suffix = suffix

    def to_broker(self, canonical):
        core = mapping.strip_fx(canonical)
        return (core + self.suffix) if core else ""

    def to_canonical(self, broker):
        core = broker[:-len(self.suffix)] if self.suffix and broker.endswith(self.suffix) else broker
        return core + ".FX"

    def is_supported(self, canonical):
        return mapping.is_forex_symbol(canonical)


# --------------------------------------------------------------------------- #
# Daily-anchor bookkeeping (capture-at-rollover; NOT a calculation/decision)
# --------------------------------------------------------------------------- #
class DailyAnchorTracker:
    """M2/M3: persists the day-start BALANCE captured at the first snapshot of each
    FTMO trading day (00:00 Europe/Prague, DST-aware). Balance excludes floating
    P/L. Idempotent per day; conflict-detected via integrity digest; survives
    restart. Never captures equity."""

    def __init__(self, path, reset_timezone="Europe/Prague"):
        self.path = path
        self.reset_timezone = reset_timezone
        self._records = {}          # trading_day -> anchor record
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
            if ok:
                self._records = dict(obj.get("records", {}))
        except FileNotFoundError:
            pass

    def _trading_day(self, now):
        from ..compliance.contract import prague_trading_day
        return prague_trading_day(now, self.reset_timezone)

    def record(self, now, balance, *, initial_balance=None, daily_loss_pct=None,
               account_id=None, profile_id=None, source_snapshot_id=None,
               safety_buffer_fraction=0.20):
        """Return the anchor record for the current Prague trading day, capturing
        the day-start BALANCE on first sight. Idempotent; flags conflict on tamper."""
        tday = self._trading_day(now)
        if tday is None:
            return None                                # tz unloadable -> caller fails closed
        existing = self._records.get(tday)
        if existing is not None:
            # idempotent; verify integrity (tamper/conflict detection)
            if not _digest_ok(existing):
                existing = dict(existing); existing["daily_anchor_conflict"] = True
            return existing
        from zoneinfo import ZoneInfo
        rec = {
            "profile_id": profile_id, "account_id": account_id,
            "trading_day": tday, "timezone": self.reset_timezone,
            "anchor_timestamp_utc": serialize.iso_utc(now),
            "anchor_timestamp_prague": now.astimezone(ZoneInfo(self.reset_timezone)).strftime("%Y-%m-%dT%H:%M:%S"),
            "day_start_balance": float(balance),
            "initial_balance": (float(initial_balance) if initial_balance is not None else None),
            "daily_loss_pct": daily_loss_pct,
            "official_loss_amount": (daily_loss_pct * initial_balance
                                     if (daily_loss_pct and initial_balance) else None),
            "internal_loss_amount": (daily_loss_pct * initial_balance * (1 - safety_buffer_fraction)
                                     if (daily_loss_pct and initial_balance) else None),
            "source_snapshot_id": source_snapshot_id,
        }
        rec["integrity_digest"] = serialize.compute_integrity_digest(rec)
        self._records[tday] = rec
        from ..bridge.atomic import atomic_write_text
        atomic_write_text(self.path, serialize.canonical_json({"records": self._records}))
        return rec


def _digest_ok(rec):
    claimed = rec.get("integrity_digest")
    body = {k: v for k, v in rec.items() if k != "integrity_digest"}
    return isinstance(claimed, str) and claimed == serialize.compute_integrity_digest(body)


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
class Mt5MarketDataProvider(MarketDataProvider):
    def __init__(self, client, symbol_map=None, history=300):
        self.client = client
        self.map = symbol_map or SymbolMap()
        self.history = history

    def get_bars(self, symbol, timeframe, now):
        if not self.map.is_supported(symbol):        # Forex-only; reject unsupported
            return None
        broker = self.map.to_broker(symbol)
        raw = self.client.copy_rates_from_pos(broker, timeframe, 0, self.history + 1)
        if not raw:
            return None
        # drop the forming (current) bar -> closed bars only
        closed = list(raw)[:-1]
        rows = []
        for r in closed:
            t = r["time"] if not hasattr(r, "time") else r.time
            rows.append({
                "open_time": datetime.fromtimestamp(int(t), tz=timezone.utc),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"])})
        if not rows:
            return None
        return Bars(symbol, timeframe, rows)


# --------------------------------------------------------------------------- #
# Account state
# --------------------------------------------------------------------------- #
class Mt5AccountStateProvider(AccountStateProvider):
    _TRADE_MODE = {mc.ACCOUNT_TRADE_MODE_DEMO: "DEMO",
                   mc.ACCOUNT_TRADE_MODE_CONTEST: "CONTEST",
                   mc.ACCOUNT_TRADE_MODE_REAL: "REAL"}

    def __init__(self, client, *, initial_balance, anchor_tracker, symbol_map=None,
                 daily_loss_pct=0.05):
        self.client = client
        self.initial_balance = float(initial_balance)   # operator config (FTMO funded balance)
        self.anchor = anchor_tracker
        self.map = symbol_map or SymbolMap()
        self.daily_loss_pct = daily_loss_pct            # FTMO 2-Step: 5% of initial

    def snapshot(self, now):
        ai = self.client.account_info()
        if ai is None:
            return None                                 # fail closed
        ti = self.client.terminal_info()
        connected = getattr(ti, "connected", None) if ti is not None else None
        positions = self.client.positions_get() or ()
        balance = float(ai.balance)
        equity = float(ai.equity)
        # M3: anchor the day-start BALANCE at the Prague rollover (not equity)
        rec = self.anchor.record(now, balance, initial_balance=self.initial_balance,
                                 daily_loss_pct=self.daily_loss_pct,
                                 account_id=getattr(ai, "login", None))
        if rec is None:
            return None                                 # tz unloadable -> fail closed
        return {
            "balance": balance,
            "current_balance": balance,
            "equity": equity,
            "initial_balance": self.initial_balance,
            "day_start_balance": rec["day_start_balance"],   # M3: balance anchor
            "trading_day": rec["trading_day"],
            "daily_anchor_conflict": bool(rec.get("daily_anchor_conflict")),
            "anchor_snapshot_id": rec.get("integrity_digest"),
            "floating_pl": float(getattr(ai, "profit", 0.0)),
            "swaps": sum(float(getattr(p, "swap", 0.0) or 0.0) for p in positions),
            "commissions": sum(float(getattr(p, "commission", 0.0) or 0.0) for p in positions),
            "open_risk_at_stop": self._open_risk(positions),
            "open_position_count": len(positions),
            "open_symbols": tuple(sorted(self.map.to_canonical(p.symbol) for p in positions)),
            "terminal_connected": connected,
            "as_of": serialize.iso_utc(now),
            "is_demo": (getattr(ai, "trade_mode", None) == mc.ACCOUNT_TRADE_MODE_DEMO),
            "account_type": self._TRADE_MODE.get(getattr(ai, "trade_mode", None), "UNKNOWN"),
            "account_currency": getattr(ai, "currency", None),
            "leverage": getattr(ai, "leverage", None),
            "margin": float(getattr(ai, "margin", 0.0)),
            "margin_free": float(getattr(ai, "margin_free", 0.0)),
            "margin_level": float(getattr(ai, "margin_level", 0.0)),
        }

    def _open_risk(self, positions):
        """Worst-case equity drop if every open position hits its stop (money from
        CURRENT price to SL). Aggregation of broker fields; no strategy/decision."""
        total = 0.0
        for p in positions:
            sl = float(getattr(p, "sl", 0.0) or 0.0)
            if sl <= 0:
                continue
            cur = float(getattr(p, "price_current", 0.0) or 0.0)
            vol = float(getattr(p, "volume", 0.0) or 0.0)
            si = self.client.symbol_info(p.symbol)
            tick_size = float(getattr(si, "trade_tick_size", 0.0) or 0.0) if si else 0.0
            tick_value = float(getattr(si, "trade_tick_value", 0.0) or 0.0) if si else 0.0
            if p.type == mc.POSITION_TYPE_BUY:
                dist = max(0.0, cur - sl)
            else:
                dist = max(0.0, sl - cur)
            if tick_size > 0 and tick_value > 0:
                total += (dist / tick_size) * tick_value * vol
            else:
                total += dist * vol                     # degraded fallback
        return total


# --------------------------------------------------------------------------- #
# Broker health
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BrokerHealthConfig:
    max_spread_points: float = 30.0
    max_slippage_points: float = 15.0
    max_quote_age_sec: float = 30.0


class Mt5BrokerHealthProvider(BrokerHealthProvider):
    def __init__(self, client, cfg=None, symbol_map=None, missing_ack_count=0,
                 slippage_source=None):
        self.client = client
        self.cfg = cfg or BrokerHealthConfig()
        self.map = symbol_map or SymbolMap()
        self._missing_ack_count = missing_ack_count
        # optional broker-derived recent-slippage observation (Phase 8D, item 8);
        # object exposing recent_points(symbol, now, point) -> float | None.
        self._slippage_source = slippage_source

    def snapshot(self, symbol, now):
        broker = self.map.to_broker(symbol)
        si = self.client.symbol_info(broker)
        if si is None:
            return None                                 # fail closed
        ti = self.client.terminal_info()
        connected = bool(getattr(ti, "connected", False)) if ti is not None else False
        point = float(getattr(si, "point", 0.0) or 0.0)
        qt = getattr(si, "time", 0) or 0
        quote_age = ((now - datetime.fromtimestamp(int(qt), tz=timezone.utc)).total_seconds()
                     if qt else self.cfg.max_quote_age_sec + 1)   # missing quote time -> stale
        stop_level_pts = float(getattr(si, "trade_stops_level", 0.0) or 0.0)
        slippage_points = self._recent_slippage(symbol, now, point)
        if slippage_points is None:
            return None                                 # configured source failed -> fail closed
        return {
            "terminal_connected": connected,
            "bridge_healthy": True,                     # bridge health is supplied by the runner side
            "spread_points": float(getattr(si, "spread", 0.0) or 0.0),
            "max_spread_points": self.cfg.max_spread_points,
            "recent_slippage_points": slippage_points,  # broker-derived (ENTER fills) or 0.0 if none
            "max_slippage_points": self.cfg.max_slippage_points,
            "missing_ack_count": self._missing_ack_count,
            "quote_age_sec": quote_age,
            "max_quote_age_sec": self.cfg.max_quote_age_sec,
            # market-gate fields
            "symbol_tradable": bool(getattr(si, "visible", True)) and self.map.is_supported(symbol),
            "market_open": connected and (getattr(si, "trade_mode", None) == mc.SYMBOL_TRADE_MODE_FULL),
            # broker constraints (normalized)
            "point": point,
            "digits": int(getattr(si, "digits", 0) or 0),
            "freeze_level": float(getattr(si, "trade_freeze_level", 0.0) or 0.0),
            "stop_level": stop_level_pts,
            "tick_size": float(getattr(si, "trade_tick_size", 0.0) or 0.0),
            "tick_value": float(getattr(si, "trade_tick_value", 0.0) or 0.0),
            "broker_min_stop_distance": stop_level_pts * point,
        }

    def _recent_slippage(self, symbol, now, point):
        """Broker-derived recent slippage in points. Without a configured source,
        report 0.0 (no observation). With a source, return its value or None (a
        source that cannot produce a trustworthy value fails the snapshot closed)."""
        if self._slippage_source is None:
            return 0.0
        try:
            return self._slippage_source.recent_points(symbol, now, point)
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# News (file-backed normalized bundle; no HTTP/scraping)
# --------------------------------------------------------------------------- #
class FileNewsDataProvider(NewsDataProvider):
    """Reads an operator-/approved-adapter-maintained normalized calendar file and
    returns the frozen NewsBundle. Fail closed on missing/malformed. The file IS
    the lawful source boundary — this provider fetches nothing."""

    def __init__(self, path):
        self.path = path

    def bundle(self, now):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                ok, obj = serialize.loads(f.read())
        except (FileNotFoundError, OSError):
            return None
        if not ok or not isinstance(obj.get("events"), list):
            return None
        return obj
