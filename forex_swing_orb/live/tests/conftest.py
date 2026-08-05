"""Fixtures for live-provider tests (Phase 8A). Deterministic; no networking;
FakeMt5Client stands in for the Windows-only MetaTrader5 package."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.live import mt5_client as mc                          # noqa: E402

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)   # on an M15 boundary


def _epoch(dt):
    return int(dt.timestamp())


def m15_rates(now=NOW, n=120, base=1.10000):
    """n closed M15 bars + 1 forming bar (open == now). Contiguous."""
    rows = []
    # forming bar opens at `now`; closed bars precede it
    for i in range(n, -1, -1):                 # i=n..0 ; i=0 is the forming bar
        ot = now - timedelta(minutes=15 * i)
        px = base + 0.0001 * ((n - i) % 5)
        rows.append((_epoch(ot), px, px + 0.0002, px - 0.0002, px + 0.0001))
    return rows


def htf_rates(now=NOW, tf_min=240, n=10, base=1.10000):
    rows = []
    for i in range(n, -1, -1):
        ot = now - timedelta(minutes=tf_min * i)
        rows.append((_epoch(ot), base, base + 0.001, base - 0.001, base + 0.0005))
    return rows


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def client():
    c = mc.FakeMt5Client()
    c.symbols["EURUSD"] = SimpleNamespace(
        name="EURUSD", digits=5, point=0.00001, spread=8, trade_stops_level=10,
        trade_freeze_level=0, trade_tick_size=0.00001, trade_tick_value=1.0,
        trade_mode=mc.SYMBOL_TRADE_MODE_FULL, visible=True, time=_epoch(NOW),
        bid=1.10000, ask=1.10008)
    c.add_rates("EURUSD", "M15", m15_rates())
    c.add_rates("EURUSD", "H1", htf_rates(tf_min=60))
    c.add_rates("EURUSD", "H4", htf_rates(tf_min=240))
    c.add_rates("EURUSD", "D1", htf_rates(tf_min=1440))
    c.account = SimpleNamespace(
        login=123, trade_mode=mc.ACCOUNT_TRADE_MODE_DEMO, balance=100000.0,
        equity=100000.0, profit=0.0, margin=0.0, margin_free=100000.0,
        margin_level=0.0, currency="USD", leverage=100)
    c.positions = []
    c.terminal = SimpleNamespace(connected=True, trade_allowed=True)
    return c
