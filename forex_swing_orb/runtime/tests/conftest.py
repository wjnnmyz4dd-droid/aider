"""Deterministic fixtures for the Phase 8D runtime-integration tests.

No networking, no real MetaTrader5: a fully-populated FakeMt5Client stands in for
the terminal, and every timestamp derives from a fixed injected ``now``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge import serialize                                # noqa: E402
from forex_swing_orb.live import mt5_client as mc                          # noqa: E402

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)   # Wed, London, M15 boundary


def _epoch(dt):
    return int(dt.timestamp())


def _m15(now=NOW, n=120, base=1.10000):
    rows = []
    for i in range(n, -1, -1):
        ot = now - timedelta(minutes=15 * i)
        px = base + 0.0001 * ((n - i) % 5)
        rows.append((_epoch(ot), px, px + 0.0002, px - 0.0002, px + 0.0001))
    return rows


def _htf(now=NOW, tf_min=240, n=10, base=1.10000):
    return [(_epoch(now - timedelta(minutes=tf_min * i)), base, base + 0.001,
             base - 0.001, base + 0.0005) for i in range(n, -1, -1)]


def make_client(positions=None):
    c = mc.FakeMt5Client()
    c.symbols["EURUSD"] = SimpleNamespace(
        name="EURUSD", digits=5, point=0.00001, spread=8, trade_stops_level=10,
        trade_freeze_level=0, trade_tick_size=0.00001, trade_tick_value=1.0,
        trade_mode=mc.SYMBOL_TRADE_MODE_FULL, visible=True, time=_epoch(NOW),
        bid=1.10000, ask=1.10008)
    for tf, m in (("M15", 15), ("H1", 60), ("H4", 240), ("D1", 1440)):
        c.add_rates("EURUSD", tf, _m15() if tf == "M15" else _htf(tf_min=m))
    c.account = SimpleNamespace(
        login=123, trade_mode=mc.ACCOUNT_TRADE_MODE_DEMO, balance=100000.0,
        equity=100000.0, profit=0.0, margin=0.0, margin_free=100000.0,
        margin_level=0.0, currency="USD", leverage=100)
    c.positions = positions or []
    c.terminal = SimpleNamespace(connected=True, trade_allowed=True)
    return c


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def client():
    return make_client()


def write_news(path, verified=True):
    bundle = {"as_of": serialize.iso_utc(NOW), "verified": verified, "events": []}
    Path(path).write_text(serialize.canonical_json(bundle), encoding="utf-8")
    return str(path)


@pytest.fixture
def env_config(tmp_path):
    """Return (env_dict, paths) for a valid DEMO FTMO 2-Step Swing configuration."""
    def _make(**over):
        bridge_root = tmp_path / "bridge"
        runtime_dir = tmp_path / "runtime"
        news = write_news(tmp_path / "news.json")
        env = {
            "SESSION_EDGE_BRIDGE_ROOT": str(bridge_root),
            "SESSION_EDGE_RUNTIME_DIR": str(runtime_dir),
            "SESSION_EDGE_SYMBOLS": "EURUSD.FX",
            "SESSION_EDGE_INITIAL_BALANCE": "100000",
            "SESSION_EDGE_ACCOUNT_CURRENCY": "USD",
            "SESSION_EDGE_FTMO_RULE_SOURCE": "ftmo.com/en/trading-objectives (2-Step)",
            "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "2026-08-05",
            "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
            "SESSION_EDGE_NEWS_FILE": news,
            "SESSION_EDGE_CADENCE_SEC": "900",
            # Phase 9A: canonical session framework (LONDON is strategy-supported)
            "SESSION_EDGE_ENABLED_SESSIONS": "LONDON",
            "SESSION_EDGE_OVERLAP_MODE": "ALLOW",
        }
        env.update(over)
        return env, {"bridge_root": bridge_root, "runtime_dir": runtime_dir,
                     "news": news}
    return _make
