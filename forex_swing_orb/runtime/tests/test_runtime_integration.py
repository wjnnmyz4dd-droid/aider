"""Phase 8D — autonomous integration & runtime-wiring tests.

Everything is deterministic, off-Windows, and networking-free: a FakeMt5Client is
injected in place of the MetaTrader5 terminal, and time is injected. Covers config
validation (fail closed), build_from_env for both services, provider construction,
broker-derived slippage, the truth source, position adoption, dashboards/health
files, graceful shutdown, and an end-to-end producer -> bridge -> manager flow.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forex_swing_orb.bridge import serialize
from forex_swing_orb.bridge.paths import BridgePaths
from forex_swing_orb.live import mt5_client as mc
from forex_swing_orb.runtime import adoption
from forex_swing_orb.runtime.config import ConfigError, load_config, password_from_env
from forex_swing_orb.runtime.slippage import BridgeSlippageSource
from forex_swing_orb.runtime.truth import Mt5TruthSource
from forex_swing_orb.runtime import wiring
from forex_swing_orb.producer.service import build_from_env as build_producer
from forex_swing_orb.manage.service import ManagerService
from conftest import NOW, make_client, write_news


SID = "0123456789abcdef"


# --------------------------------------------------------------------------- #
# 1. Config loading + validation (fail closed)
# --------------------------------------------------------------------------- #
def test_config_valid(env_config):
    env, _ = env_config()
    cfg = load_config(env=env)
    assert cfg.symbols == ("EURUSD.FX",)
    assert cfg.initial_balance == 100000.0
    assert cfg.ftmo_profile_verified is True
    assert cfg.reset_timezone == "Europe/Prague"
    assert "password" not in cfg.public_dict() and "mt5_login" not in cfg.public_dict()


@pytest.mark.parametrize("drop", [
    "SESSION_EDGE_BRIDGE_ROOT", "SESSION_EDGE_RUNTIME_DIR", "SESSION_EDGE_SYMBOLS",
    "SESSION_EDGE_INITIAL_BALANCE", "SESSION_EDGE_ACCOUNT_CURRENCY",
    "SESSION_EDGE_FTMO_RULE_SOURCE", "SESSION_EDGE_FTMO_RULE_VERIFIED_AT",
    "SESSION_EDGE_FTMO_PROFILE_VERIFIED", "SESSION_EDGE_NEWS_FILE"])
def test_config_missing_required_fails_closed(env_config, drop):
    env, _ = env_config()
    env.pop(drop)
    with pytest.raises(ConfigError):
        load_config(env=env)


def test_config_unverified_profile_rejected(env_config):
    env, _ = env_config(SESSION_EDGE_FTMO_PROFILE_VERIFIED="false")
    with pytest.raises(ConfigError):
        load_config(env=env)


def test_config_non_forex_symbol_rejected(env_config):
    env, _ = env_config(SESSION_EDGE_SYMBOLS="XAUUSD.FX")
    with pytest.raises(ConfigError):
        load_config(env=env)


def test_config_bad_timezone_rejected(env_config):
    env, _ = env_config(SESSION_EDGE_RESET_TIMEZONE="Not/AZone")
    with pytest.raises(ConfigError):
        load_config(env=env)


def test_config_bad_balance_rejected(env_config):
    env, _ = env_config(SESSION_EDGE_INITIAL_BALANCE="0")
    with pytest.raises(ConfigError):
        load_config(env=env)
    env2, _ = env_config(SESSION_EDGE_INITIAL_BALANCE="not-a-number")
    with pytest.raises(ConfigError):
        load_config(env=env2)


def test_config_json_file_and_env_override(tmp_path, env_config):
    env, paths = env_config()
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(serialize.canonical_json({
        "bridge_root": str(paths["bridge_root"]), "runtime_dir": str(paths["runtime_dir"]),
        "symbols": ["EURUSD.FX", "GBPUSD.FX"], "initial_balance": 200000,
        "account_currency": "USD", "ftmo_rule_source": "x",
        "ftmo_rule_source_verified_at": "2026-08-05", "ftmo_profile_verified": True,
        "news_file": paths["news"]}), encoding="utf-8")
    # env overrides the file's initial_balance
    cfg = load_config(env={"SESSION_EDGE_INITIAL_BALANCE": "100000"},
                      config_path=str(cfg_file))
    assert cfg.initial_balance == 100000.0
    assert cfg.symbols == ("EURUSD.FX", "GBPUSD.FX")


def test_config_malformed_json_and_unknown_keys(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(env={}, config_path=str(bad))
    unk = tmp_path / "unk.json"
    unk.write_text(serialize.canonical_json({"nope": 1}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(env={}, config_path=str(unk))


def test_password_from_env_isolated():
    assert password_from_env({"SESSION_EDGE_MT5_PASSWORD": "s3cret"}) == "s3cret"
    assert password_from_env({}) is None


# --------------------------------------------------------------------------- #
# 2. Compliance / profile wiring (fail closed)
# --------------------------------------------------------------------------- #
def test_build_profile_verified(env_config):
    cfg = load_config(env=env_config()[0])
    assert wiring.build_profile(cfg).verification_error() is None


def test_build_compliance_config_rejects_unusable_profile(env_config):
    # a config that validates but yields an unusable profile (bad currency? no —
    # use an initial balance the profile rejects is caught earlier). Force via a
    # profile-unusable timezone bypass is impossible after config validation, so
    # assert the fail-closed path through build_profile using a hand-built cfg.
    from forex_swing_orb.runtime.config import RuntimeConfig
    cfg = RuntimeConfig(
        bridge_root="/x", runtime_dir="/x", symbols=("EURUSD.FX",),
        initial_balance=100000.0, account_currency="USD", ftmo_rule_source=None,
        ftmo_rule_source_verified_at=None, ftmo_profile_verified=True,
        news_file="/x/news.json")
    with pytest.raises(ConfigError):
        wiring.build_compliance_config(cfg)


# --------------------------------------------------------------------------- #
# 3. Provider construction from config
# --------------------------------------------------------------------------- #
def test_provider_construction(env_config, client):
    cfg = load_config(env=env_config()[0])
    cfg.ensure_runtime_dir()
    market = wiring.build_market_provider(client, cfg)
    account = wiring.build_account_provider(client, cfg)
    broker = wiring.build_broker_provider(client, cfg)
    news = wiring.build_news_provider(cfg)
    assert market.get_bars("EURUSD.FX", "M15", NOW) is not None
    snap = account.snapshot(NOW)
    assert snap["is_demo"] is True and snap["day_start_balance"] == 100000.0
    bh = broker.snapshot("EURUSD.FX", NOW)
    assert bh is not None and bh["recent_slippage_points"] == 0.0
    assert news.bundle(NOW) is not None


# --------------------------------------------------------------------------- #
# 4. Broker-derived slippage (item 8)
# --------------------------------------------------------------------------- #
def test_slippage_source_reads_enter_fills(tmp_path):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    rec = {"signal_id": SID, "symbol": "EURUSD.FX",
           "completed_timestamp": serialize.iso_utc(NOW),
           "execution": {"slippage": 0.00003}}      # 3 points at point=0.00001
    (paths.results / f"{SID}.{SID}.json").write_text(
        serialize.canonical_json(rec), encoding="utf-8")
    src = BridgeSlippageSource(tmp_path / "bridge")
    assert src.recent_points("EURUSD.FX", NOW, 0.00001) == pytest.approx(3.0)
    assert src.recent_points("GBPUSD.FX", NOW, 0.00001) == 0.0     # no fills -> 0
    assert src.recent_points("EURUSD.FX", NOW, 0.0) is None        # bad point -> fail closed


def test_broker_provider_uses_slippage_source(tmp_path, env_config, client):
    env, paths = env_config()
    cfg = load_config(env=env)
    bp = BridgePaths(paths["bridge_root"]).ensure()
    rec = {"signal_id": SID, "symbol": "EURUSD.FX",
           "completed_timestamp": serialize.iso_utc(NOW),
           "execution": {"slippage": 0.00005}}
    (bp.results / f"{SID}.{SID}.json").write_text(
        serialize.canonical_json(rec), encoding="utf-8")
    bh = wiring.build_broker_provider(client, cfg).snapshot("EURUSD.FX", NOW)
    assert bh["recent_slippage_points"] == pytest.approx(5.0)


def test_broker_provider_fails_closed_on_bad_slippage_source(client):
    from forex_swing_orb.live import Mt5BrokerHealthProvider

    class _Boom:
        def recent_points(self, *_):
            raise RuntimeError("boom")
    bh = Mt5BrokerHealthProvider(client, slippage_source=_Boom()).snapshot("EURUSD.FX", NOW)
    assert bh is None                                 # source failure -> fail closed


# --------------------------------------------------------------------------- #
# 5. Truth source
# --------------------------------------------------------------------------- #
def test_truth_source_reads_broker(client):
    pos = SimpleNamespace(ticket=5000001, symbol="EURUSD", type=mc.POSITION_TYPE_BUY,
                          volume=0.1, price_open=1.10000, sl=1.09800, tp=1.10600,
                          price_current=1.10050, comment=SID)
    client.positions = [pos]
    t = Mt5TruthSource(client)
    assert t.terminal_connected() is True
    assert t.position_by_ticket(5000001) is pos
    assert t.position_by_ticket(999) is None
    assert t.symbol_info("EURUSD") is not None


def test_truth_source_disconnected(client):
    client.terminal = SimpleNamespace(connected=False)
    assert Mt5TruthSource(client).terminal_connected() is False


# --------------------------------------------------------------------------- #
# 6. Position adoption
# --------------------------------------------------------------------------- #
def _archive_enter(paths, sid=SID, entry=1.10000, sl=1.09800, tp=1.10600):
    instr = {"signal_id": sid, "symbol": "EURUSD.FX", "direction": "LONG",
             "entry_price": entry, "stop_loss": sl, "take_profit": tp}
    (paths.archive_accepted / f"{sid}.json").write_text(
        serialize.canonical_json(instr), encoding="utf-8")


def test_adoption_recovers_initial_reference(tmp_path, client):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    _archive_enter(paths)
    client.positions = [SimpleNamespace(
        ticket=5000001, symbol="EURUSD", type=mc.POSITION_TYPE_BUY, volume=0.1,
        price_open=1.10002, sl=1.09800, tp=1.10600, price_current=1.10050, comment=SID)]
    regs = adoption.discover_registrations(Mt5TruthSource(client), paths, [])
    assert len(regs) == 1
    r = regs[0]
    assert r["signal_id"] == SID and r["initial_stop"] == 1.09800
    assert r["entry"] == 1.10000 and r["symbol"] == "EURUSD"


def test_adoption_skips_untracked_without_reference(tmp_path, client):
    paths = BridgePaths(tmp_path / "bridge").ensure()      # no archived ENTER instr
    client.positions = [SimpleNamespace(
        ticket=5000001, symbol="EURUSD", type=mc.POSITION_TYPE_BUY, volume=0.1,
        price_open=1.10002, sl=1.09800, tp=1.10600, price_current=1.10050, comment=SID)]
    assert adoption.discover_registrations(Mt5TruthSource(client), paths, []) == []


def test_adoption_skips_non_signal_comment_and_tracked(tmp_path, client):
    paths = BridgePaths(tmp_path / "bridge").ensure()
    _archive_enter(paths)
    client.positions = [
        SimpleNamespace(ticket=1, symbol="EURUSD", type=0, volume=0.1, price_open=1.1,
                        sl=1.09, tp=1.11, price_current=1.10, comment="manual-note"),
        SimpleNamespace(ticket=2, symbol="EURUSD", type=0, volume=0.1, price_open=1.1,
                        sl=1.09, tp=1.11, price_current=1.10, comment=SID)]
    assert adoption.discover_registrations(Mt5TruthSource(client), paths, [SID]) == []


# --------------------------------------------------------------------------- #
# 7. ProducerService.build_from_env (item 1) + dashboards/health (item 6)
# --------------------------------------------------------------------------- #
def test_producer_build_from_env_and_cycle(env_config, client):
    env, paths = env_config()
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    svc.runner.preflight(NOW)                          # DEMO/FTMO gate passes
    svc.run_forever(max_cycles=1)                      # one deterministic cycle
    health = serialize.loads((paths["runtime_dir"] / "producer_health.json")
                             .read_text(encoding="utf-8"))[1]
    assert health["mode"] == "DEMO" and health["demo_verified"] is True
    comp = serialize.loads((paths["runtime_dir"] / "compliance_status.json")
                           .read_text(encoding="utf-8"))[1]
    assert comp["program"] == "FTMO_TWO_STEP" and comp["account_type"] == "FTMO_SWING"
    assert comp["official_daily_level"] == 95000.0 and comp["official_max_level"] == 90000.0


def test_producer_refuses_non_demo(env_config):
    c = make_client()
    c.account.trade_mode = mc.ACCOUNT_TRADE_MODE_REAL     # not a demo account
    env, _ = env_config()
    svc = build_producer(env=env, client=c, now_fn=lambda: NOW)
    from forex_swing_orb.producer.contract import RunnerRefused
    with pytest.raises(RunnerRefused):
        svc.runner.preflight(NOW)


def test_producer_graceful_shutdown_flag(env_config, client):
    env, _ = env_config()
    svc = build_producer(env=env, client=client, now_fn=lambda: NOW)
    svc.start()
    svc._handle_signal()                               # simulate SIGINT
    assert svc._stop is True


# --------------------------------------------------------------------------- #
# 8. ManagerService.build_from_env (item 2) + health
# --------------------------------------------------------------------------- #
def test_manager_build_from_env_and_status(env_config, client):
    env, paths = env_config()
    svc = ManagerService.build_from_env(env=env, client=client, now_fn=lambda: NOW)
    st = svc.status(NOW)
    assert st["service_state"] == "READY" and st["terminal_connected"] is True
    svc.run_once(NOW)                                  # no positions -> no-op, health written
    health = serialize.loads((paths["runtime_dir"] / "manager_health.json")
                             .read_text(encoding="utf-8"))[1]
    assert health["tracked_tickets"] == 0


# --------------------------------------------------------------------------- #
# 9. End-to-end: producer -> bridge -> manager (FakeMt5Client)
# --------------------------------------------------------------------------- #
def test_e2e_producer_bridge_manager(env_config):
    env, paths = env_config()
    client = make_client()

    # producer: build + run a cycle through the fully-wired live pipeline
    prod = build_producer(env=env, client=client, now_fn=lambda: NOW)
    prod.runner.preflight(NOW)
    prod.run_forever(max_cycles=1)

    # a fill occurs (the EA executes an approved ENTER and stamps the signal_id);
    # represent it: archive the ENTER instruction + open the broker position.
    bp = BridgePaths(paths["bridge_root"]).ensure()
    _archive_enter(bp)
    client.positions = [SimpleNamespace(
        ticket=5000001, symbol="EURUSD", type=mc.POSITION_TYPE_BUY, volume=0.1,
        price_open=1.10000, sl=1.09800, tp=1.10600, price_current=1.10050, comment=SID)]

    # manager: build + run -> adopts the position and tracks it
    mgr = ManagerService.build_from_env(env=env, client=client, now_fn=lambda: NOW)
    mgr.run_once(NOW)
    assert SID in mgr.pm.states
    assert mgr.pm.states[SID]["ticket"] == 5000001
    assert mgr.status(NOW)["tracked_tickets"] == 1


# --------------------------------------------------------------------------- #
# 10. No networking in the runtime layer
# --------------------------------------------------------------------------- #
def test_runtime_no_networking():
    import inspect
    from forex_swing_orb.runtime import (config, wiring as w, truth, slippage,
                                         adoption as ad, status)
    for mod in (config, w, truth, slippage, ad, status):
        src = inspect.getsource(mod).lower()
        for tok in ("import socket", "import requests", "import urllib", "http.client",
                    "urllib.request", "socket.socket", "import selenium", "webdriver",
                    "requests.get", "os.system("):
            assert tok not in src, f"{mod.__name__}: {tok}"
