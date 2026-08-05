"""Live-input provider interfaces + deterministic validation (Phase 7A).

The runner depends only on these abstract interfaces. Concrete LIVE providers
(MT5-backed market/account, an approved news adapter) are OUT OF SCOPE for this
phase and are NOT implemented here — this phase uses mock providers (see
``mock_providers.py``) and the existing mock MT5/bridge harness. No provider in
this module performs networking, scraping, or HTTP.

Validation is deterministic and FAILS CLOSED: any missing / stale / future /
unclosed / gapped / non-Forex input yields a rejection reason code, never a
silent pass.
"""

from __future__ import annotations

import abc

from ..bridge import serialize
from ..compliance import mapping
from .contract import RunnerReason, tf_minutes


# --------------------------------------------------------------------------- #
# Abstract provider interfaces
# --------------------------------------------------------------------------- #
class MarketDataProvider(abc.ABC):
    """Forex-only, closed-bars-only OHLC bars. Never returns a future/unclosed bar."""

    @abc.abstractmethod
    def get_bars(self, symbol, timeframe, now):
        """Return a Bars object (see :class:`Bars`) or None if unavailable."""


class AccountStateProvider(abc.ABC):
    @abc.abstractmethod
    def snapshot(self, now):
        """Return an account-state dict or None if unavailable. Required keys:
        balance, equity, initial_balance, daily_anchor_equity, current_daily_loss,
        open_risk_at_stop, open_position_count, open_symbols, terminal_connected,
        as_of, is_demo, account_type."""


class NewsDataProvider(abc.ABC):
    @abc.abstractmethod
    def bundle(self, now):
        """Return a normalized NewsBundle dict (as consumed by the compliance
        news gate) or None. Operates 24/7 incl. weekends/market-closed."""


class BrokerHealthProvider(abc.ABC):
    @abc.abstractmethod
    def snapshot(self, symbol, now):
        """Return a broker-health dict (compliance broker-health contract) plus
        ``symbol_tradable`` / ``market_open`` for the market gate, or None."""


# --------------------------------------------------------------------------- #
# Bars value object — closed OHLC bars with a monotonic UTC index
# --------------------------------------------------------------------------- #
class Bars:
    """A minimal, dependency-light closed-bar series. ``rows`` is a list of
    dicts {open_time(datetime UTC), open, high, low, close}. ``timeframe`` is a
    label (M15/H1/H4/D1). The value object is deliberately not pandas so
    validation stays pure; the strategy adapter converts to a DataFrame."""

    def __init__(self, symbol, timeframe, rows):
        self.symbol = symbol
        self.timeframe = timeframe
        self.rows = list(rows)

    @property
    def last(self):
        return self.rows[-1] if self.rows else None

    def version(self):
        """Deterministic content digest for audit/cycle-id."""
        payload = serialize.canonical_json(
            {"symbol": self.symbol, "tf": self.timeframe,
             "last": serialize.iso_utc(self.last["open_time"]) if self.rows else None,
             "n": len(self.rows)})
        import hashlib
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Deterministic validation (fail closed)
# --------------------------------------------------------------------------- #
def _is_weekend_gap(prev_close, nxt_open):
    """A legitimate FX gap: previous bar closes Friday (UTC) and next opens
    Sunday/Monday. Deterministic, no wall clock."""
    return prev_close.isoweekday() == 5 and nxt_open.isoweekday() in (6, 7, 1)


def validate_bars(bars, timeframe, now, max_age_sec, continuity_bars, min_bars):
    """Return (ok, reason_code). Deterministic; fails closed.

    Checks: availability, Forex-only symbol, sufficient history, monotonic &
    unique index, no future bar, last bar CLOSED, freshness, and recent
    continuity (allowing weekend gaps)."""
    if bars is None or bars.last is None:
        return (False, RunnerReason.DATA_UNAVAILABLE)
    if not mapping.is_forex_symbol(bars.symbol):
        return (False, RunnerReason.DATA_NOT_FOREX)
    rows = bars.rows
    if len(rows) < min_bars:
        return (False, RunnerReason.DATA_INSUFFICIENT)

    m = tf_minutes(timeframe)
    step = m * 60

    # monotonic strictly increasing, unique
    for i in range(1, len(rows)):
        if rows[i]["open_time"] <= rows[i - 1]["open_time"]:
            return (False, RunnerReason.DATA_GAP)

    last_open = rows[-1]["open_time"]
    last_close = _add_sec(last_open, step)
    # last bar must be fully closed (no unclosed bar), and no future bar
    if last_close > now:
        return (False, RunnerReason.DATA_UNCLOSED_BAR)
    if last_open > now:
        return (False, RunnerReason.DATA_FUTURE_BAR)
    # freshness: the latest closed bar must be at most one bar-length (+ tolerance)
    # behind — a per-timeframe rule (a D1 bar is hours old by construction).
    if (now - last_close).total_seconds() > (step + max_age_sec):
        return (False, RunnerReason.DATA_STALE)

    # recent continuity (allow weekend gaps)
    window = rows[-continuity_bars:] if continuity_bars > 0 else rows
    for i in range(1, len(window)):
        prev_open = window[i - 1]["open_time"]
        cur_open = window[i]["open_time"]
        gap = (cur_open - prev_open).total_seconds()
        if gap == step:
            continue
        prev_close = _add_sec(prev_open, step)
        if gap > step and _is_weekend_gap(prev_close, cur_open):
            continue
        return (False, RunnerReason.DATA_GAP)
    return (True, RunnerReason.OK)


def validate_account(snap, now, max_age_sec):
    """Return (ok, reason_code). Fail closed on missing/stale/unverified."""
    if not isinstance(snap, dict):
        return (False, RunnerReason.ACCOUNT_UNAVAILABLE)
    for k in ("balance", "equity", "initial_balance", "daily_anchor_equity",
              "current_daily_loss", "open_risk_at_stop", "open_position_count",
              "open_symbols", "terminal_connected", "as_of"):
        if snap.get(k) is None:
            return (False, RunnerReason.ACCOUNT_UNAVAILABLE)
    as_of = serialize.parse_iso(snap.get("as_of"))
    if as_of is None:
        return (False, RunnerReason.ACCOUNT_UNAVAILABLE)
    if abs((now - as_of).total_seconds()) > max_age_sec:
        return (False, RunnerReason.ACCOUNT_STALE)
    return (True, RunnerReason.OK)


def _add_sec(dt, seconds):
    from datetime import timedelta
    return dt + timedelta(seconds=seconds)
