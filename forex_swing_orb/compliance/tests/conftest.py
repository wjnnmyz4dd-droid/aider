"""Deterministic fixtures for the FTMO Compliance Engine tests. No networking,
no wall clock (all timestamps derive from a fixed injected ``now``)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]   # .../aider
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize                              # noqa: E402

# A fixed weekday during the London session (Wed 2026-01-07 10:00 UTC).
NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
SUNDAY = datetime(2026, 1, 11, 10, 0, 0, tzinfo=timezone.utc)
FRIDAY = datetime(2026, 1, 9, 21, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def make_candidate():
    def _make(**over):
        c = {
            "signal_id": "0123456789abcdef",
            "symbol": "EURUSD.FX",
            "direction": "LONG",
            "entry": 1.10000,
            "stop_loss": 1.09500,
            "take_profit": 1.11000,
            "risk_fraction": 0.005,
            "mtf": {"daily_bias": "UP", "h4_structure": "UP",
                    "h1_setup": "BREAKOUT", "m15_timing": "RETEST", "aligned": True},
        }
        c.update(over)
        return c
    return _make


@pytest.fixture
def make_account():
    def _make(**over):
        a = {
            "daily_anchor_equity": 100000.0,
            "initial_balance": 100000.0,
            "equity": 100000.0,
            "current_daily_loss": 0.0,
            "open_risk_at_stop": 0.0,
            "open_position_count": 0,
            "open_symbols": (),
        }
        a.update(over)
        return a
    return _make


@pytest.fixture
def make_market():
    def _make(**over):
        m = {"symbol_tradable": True, "market_open": True}
        m.update(over)
        return m
    return _make


@pytest.fixture
def make_broker():
    def _make(**over):
        b = {
            "terminal_connected": True,
            "bridge_healthy": True,
            "spread_points": 5.0,
            "max_spread_points": 20.0,
            "recent_slippage_points": 1.0,
            "max_slippage_points": 10.0,
            "missing_ack_count": 0,
            "quote_age_sec": 1.0,
            "max_quote_age_sec": 30.0,
        }
        b.update(over)
        return b
    return _make


@pytest.fixture
def make_news():
    def _make(events=None, as_of=None, **over):
        n = {"as_of": as_of or serialize.iso_utc(NOW), "verified": True,
             "events": events if events is not None else []}
        n.update(over)
        return n
    return _make


@pytest.fixture
def make_event():
    """Build a normalized scheduled news event at ``offset_min`` from NOW."""
    def _make(currency="USD", impact="HIGH", offset_min=0, event_id="EV1",
              verification_state="VERIFIED", when=None):
        base = when or NOW
        ts = serialize.iso_utc(base + timedelta(minutes=offset_min))
        return {"event_id": event_id, "currency": currency, "impact": impact,
                "event_timestamp": ts, "verification_state": verification_state,
                "event_name": f"{currency} {impact}"}
    return _make
