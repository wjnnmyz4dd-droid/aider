"""Phase 8A live-provider tests (FakeMt5Client; no networking, no real terminal)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.compliance import gates as cgates
from forex_swing_orb.live import (BrokerHealthConfig, DailyAnchorTracker,
                                  FileNewsDataProvider, Mt5AccountStateProvider,
                                  Mt5BrokerHealthProvider, Mt5MarketDataProvider,
                                  SymbolMap)
from forex_swing_orb.live import mt5_client as mc
from forex_swing_orb.producer.providers import validate_account, validate_bars
from conftest import NOW, m15_rates


# --------------------------------------------------------------------------- #
# Market provider
# --------------------------------------------------------------------------- #
def test_market_closed_bars_only_and_valid(client):
    p = Mt5MarketDataProvider(client, history=120)
    bars = p.get_bars("EURUSD.FX", "M15", NOW)
    assert bars is not None and bars.symbol == "EURUSD.FX"
    # forming bar dropped: last closed open is 09:45 (== last_closed_open at 10:00)
    assert bars.last["open_time"] == NOW - timedelta(minutes=15)
    ok, reason = validate_bars(bars, "M15", NOW, 120, 8, 60)
    assert ok, reason


def test_market_rejects_unsupported_symbols(client):
    p = Mt5MarketDataProvider(client)
    for bad in ("XAUUSD.FX", "BTCUSD.FX", "SPX500.FX", "US30.FX", "EURUSD"):
        assert p.get_bars(bad, "M15", NOW) is None


def test_market_no_rates_returns_none(client):
    p = Mt5MarketDataProvider(client)
    assert p.get_bars("GBPUSD.FX", "M15", NOW) is None      # no rates loaded


def test_market_deterministic(client):
    p = Mt5MarketDataProvider(client, history=120)
    a = p.get_bars("EURUSD.FX", "M15", NOW)
    b = p.get_bars("EURUSD.FX", "M15", NOW)
    assert [r["open_time"] for r in a.rows] == [r["open_time"] for r in b.rows]
    assert a.version() == b.version()


def test_market_all_timeframes(client):
    p = Mt5MarketDataProvider(client, history=120)
    for tf in ("M15", "H1", "H4", "D1"):
        assert p.get_bars("EURUSD.FX", tf, NOW) is not None


# --------------------------------------------------------------------------- #
# Account provider
# --------------------------------------------------------------------------- #
def _account(client, tmp_path, initial_balance=100000.0):
    tracker = DailyAnchorTracker(str(tmp_path / "anchor.json"))
    return Mt5AccountStateProvider(client, initial_balance=initial_balance,
                                   anchor_tracker=tracker)


def test_account_snapshot_valid(client, tmp_path):
    snap = _account(client, tmp_path).snapshot(NOW)
    ok, reason = validate_account(snap, NOW, 60)
    assert ok, reason
    assert snap["is_demo"] is True and snap["account_type"] == "DEMO"
    assert snap["account_currency"] == "USD" and snap["leverage"] == 100
    assert snap["day_start_balance"] == 100000.0        # M3: balance anchor
    assert snap["trading_day"] is not None


def test_account_none_when_unavailable(client, tmp_path):
    client.account = None
    assert _account(client, tmp_path).snapshot(NOW) is None


def test_account_disconnect_reflected(client, tmp_path):
    client.terminal = SimpleNamespace(connected=False)
    snap = _account(client, tmp_path).snapshot(NOW)
    assert snap["terminal_connected"] is False


def test_account_balance_anchor_persists_and_ignores_equity(client, tmp_path):
    prov = _account(client, tmp_path)
    prov.snapshot(NOW)                                    # day-start BALANCE captured @ 100000
    client.account.equity = 96000.0                      # equity (floating) dropped intraday
    client.account.balance = 100000.0                    # balance unchanged (no closed trades)
    snap = prov.snapshot(NOW)
    assert snap["day_start_balance"] == 100000.0          # anchor is balance, unchanged by equity
    assert snap["equity"] == 96000.0                      # equity tracked separately for breach
    # "restart": new tracker over same file -> balance anchor survives
    prov2 = _account(client, tmp_path)
    assert prov2.snapshot(NOW)["day_start_balance"] == 100000.0


def test_account_open_risk_and_symbols(client, tmp_path):
    client.positions = [SimpleNamespace(ticket=1, symbol="EURUSD", type=mc.POSITION_TYPE_BUY,
                                        volume=1.0, price_open=1.10000, sl=1.09800,
                                        tp=1.10600, price_current=1.10000)]
    snap = _account(client, tmp_path).snapshot(NOW)
    assert snap["open_position_count"] == 1
    assert snap["open_symbols"] == ("EURUSD.FX",)
    # risk = (1.10000-1.09800)/0.00001 * 1.0 * 1.0 = 200
    assert snap["open_risk_at_stop"] == pytest.approx(200.0)


def test_account_deterministic(client, tmp_path):
    p = _account(client, tmp_path)
    assert p.snapshot(NOW) == p.snapshot(NOW)


# --------------------------------------------------------------------------- #
# Broker health provider
# --------------------------------------------------------------------------- #
def test_broker_snapshot_valid_passes_compliance_gate(client):
    p = Mt5BrokerHealthProvider(client)
    bh = p.snapshot("EURUSD.FX", NOW)
    assert bh is not None
    v = cgates.gate_broker_health(bh, NOW)
    assert v.passed, v.reason_codes
    assert bh["symbol_tradable"] is True and bh["market_open"] is True
    assert bh["broker_min_stop_distance"] == pytest.approx(10 * 0.00001)


def test_broker_missing_symbol_fail_closed(client):
    assert Mt5BrokerHealthProvider(client).snapshot("GBPUSD.FX", NOW) is None


def test_broker_stale_quote_detected(client):
    client.symbols["EURUSD"].time = int((NOW - timedelta(minutes=5)).timestamp())
    bh = Mt5BrokerHealthProvider(client, BrokerHealthConfig(max_quote_age_sec=30)).snapshot("EURUSD.FX", NOW)
    v = cgates.gate_broker_health(bh, NOW)
    assert not v.passed                                   # stale -> MARKET_DATA_STALE


def test_broker_disconnect_market_closed(client):
    client.terminal = SimpleNamespace(connected=False)
    bh = Mt5BrokerHealthProvider(client).snapshot("EURUSD.FX", NOW)
    assert bh["terminal_connected"] is False and bh["market_open"] is False


def test_broker_deterministic(client):
    p = Mt5BrokerHealthProvider(client)
    assert p.snapshot("EURUSD.FX", NOW) == p.snapshot("EURUSD.FX", NOW)


# --------------------------------------------------------------------------- #
# News provider
# --------------------------------------------------------------------------- #
def test_news_reads_normalized_bundle(tmp_path):
    path = tmp_path / "news.json"
    bundle = {"as_of": serialize.iso_utc(NOW), "verified": True,
              "events": [{"event_id": "E1", "currency": "USD", "impact": "HIGH",
                          "event_timestamp": serialize.iso_utc(NOW),
                          "verification_state": "VERIFIED", "event_name": "CPI",
                          "source": "calendar"}]}
    path.write_text(serialize.canonical_json(bundle), encoding="utf-8")
    got = FileNewsDataProvider(str(path)).bundle(NOW)
    assert got["events"][0]["event_id"] == "E1" and got["verified"] is True


def test_news_missing_file_fail_closed(tmp_path):
    assert FileNewsDataProvider(str(tmp_path / "absent.json")).bundle(NOW) is None


def test_news_malformed_fail_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    assert FileNewsDataProvider(str(path)).bundle(NOW) is None
    path.write_text(serialize.canonical_json({"as_of": "x"}), encoding="utf-8")   # no events
    assert FileNewsDataProvider(str(path)).bundle(NOW) is None


# --------------------------------------------------------------------------- #
# Boundary / integration
# --------------------------------------------------------------------------- #
def test_providers_are_readonly_no_networking():
    import inspect
    from forex_swing_orb.live import providers, mt5_client
    for mod in (providers, mt5_client):
        src = inspect.getsource(mod).lower()
        for tok in ("import socket", "import requests", "import urllib", "http.client",
                    "urllib.request", "socket.socket", "subprocess", "os.system(",
                    "import selenium", "webdriver", "requests.get"):
            assert tok not in src, f"{mod.__name__}: {tok}"


def test_symbol_map_roundtrip():
    m = SymbolMap(suffix=".m")
    assert m.to_broker("EURUSD.FX") == "EURUSD.m"
    assert m.to_canonical("EURUSD.m") == "EURUSD.FX"
    assert m.is_supported("EURUSD.FX") and not m.is_supported("XAUUSD.FX")


def test_real_client_factory_unavailable_off_windows():
    with pytest.raises(RuntimeError):
        mc.create_real_client()          # MetaTrader5 not importable here -> clear error
