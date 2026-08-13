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
from forex_swing_orb.compliance import (ComplianceConfig, FtmoProfile,      # noqa: E402
                                        prague_trading_day)

# A fixed weekday during the London session (Wed 2026-01-07 10:00 UTC).
NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)


def verified_profile(**over):
    """A verified FTMO 2-Step Swing profile for tests (Phase 8C)."""
    f = dict(initial_balance=100000.0, account_currency="USD",
             rule_source="ftmo.com/en/trading-objectives (2-Step)",
             rule_source_verified_at="2026-08-05", profile_verified=True)
    f.update(over)
    return FtmoProfile(**f)


def verified_config(**over):
    return ComplianceConfig(profile=verified_profile(), **over)
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
            # M9: authoritative execution volume. loss-at-stop = 0.005/1e-5 * 1.0 * 0.10
            # = 50.0 <= permitted 0.005*100000 = 500.0 (EURUSD tick metadata below).
            "volume": 0.10,
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
            "day_start_balance": 100000.0,          # M3: balance anchor
            "initial_balance": 100000.0,
            "equity": 100000.0,
            "trading_day": None,          # staleness is exercised explicitly in the 8C suite
            "open_position_count": 0,
            "open_symbols": (),
        }
        a.update(over)
        # H2: day-start equity defaults to the (possibly overridden) day-start
        # balance — the realistic "no floating P/L at rollover" case — so the
        # max(balance, equity) reference stays consistent unless a test sets it.
        a.setdefault("day_start_equity", a["day_start_balance"])
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
            # M9: symbol tick/volume metadata for the authoritative risk recompute
            # (EURUSD-like 5-digit; tick_value account-currency-denominated).
            "tick_size": 0.00001, "tick_value": 1.0,
            "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
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
