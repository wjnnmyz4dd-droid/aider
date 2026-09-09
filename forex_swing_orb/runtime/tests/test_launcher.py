"""Deterministic tests for the automatic launcher's pure logic (no Windows, no
MetaTrader5, no subprocesses). The MT5-touching / process-spawning layer is
pragma-excluded and out of scope here."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.live import mt5_client as mc                          # noqa: E402
from forex_swing_orb.runtime import launcher as L                          # noqa: E402


def test_bridge_root_from_data_path():
    got = L.bridge_root_from_data_path(r"C:\Users\me\AppData\Roaming\MetaQuotes\Terminal\ABC")
    assert got.endswith("session_edge_bridge")
    assert "Files" in got and "MQL5" in got


def test_account_is_demo():
    assert L.account_is_demo(mc.ACCOUNT_TRADE_MODE_DEMO) is True
    assert L.account_is_demo(mc.ACCOUNT_TRADE_MODE_REAL) is False
    assert L.account_is_demo(mc.ACCOUNT_TRADE_MODE_CONTEST) is False
    assert L.account_is_demo(None) is False


def test_attestation_ok():
    assert L.attestation_ok(flag=True) is True
    assert L.attestation_ok(flag=False) is False
    assert L.attestation_ok(flag=False, tty_confirm="VERIFIED") is True
    assert L.attestation_ok(flag=False, tty_confirm=" VERIFIED ") is True
    assert L.attestation_ok(flag=False, tty_confirm="yes") is False
    assert L.attestation_ok(flag=False, tty_confirm="") is False


def _env(**over):
    base = {"PATH": "x", "SESSION_EDGE_CONFIG": "C:\\stale.json"}
    kw = dict(bridge_root=r"C:\T\MQL5\Files\session_edge_bridge",
              runtime_dir=r"C:\T\MQL5\Files\session_edge_runtime",
              news_file=r"C:\T\MQL5\Files\session_edge_runtime\news_bundle.json",
              symbols=("EURUSD.FX", "GBPUSD.FX"), symbol_suffix="", initial_balance=100000.0,
              account_currency="USD", ftmo_source="src", ftmo_verified_at="2026-08-10")
    kw.update(over)
    return L.build_env(base, **kw)


def test_build_env_sets_all_required_keys():
    env = _env()
    required = [
        "SESSION_EDGE_BRIDGE_ROOT", "SESSION_EDGE_RUNTIME_DIR", "SESSION_EDGE_NEWS_FILE",
        "SESSION_EDGE_SYMBOLS", "SESSION_EDGE_INITIAL_BALANCE",
        "SESSION_EDGE_ACCOUNT_CURRENCY", "SESSION_EDGE_FTMO_RULE_SOURCE",
        "SESSION_EDGE_FTMO_RULE_VERIFIED_AT", "SESSION_EDGE_FTMO_PROFILE_VERIFIED",
        "SESSION_EDGE_ENABLED_SESSIONS", "SESSION_EDGE_OVERLAP_MODE",
        "SESSION_EDGE_CALENDAR_ENABLED", "SESSION_EDGE_CALENDAR_PROVIDER",
        "SESSION_EDGE_CALENDAR_OUTPUT_FILE",
    ]
    for k in required:
        assert k in env, f"missing {k}"
    assert env["SESSION_EDGE_SYMBOLS"] == "EURUSD.FX,GBPUSD.FX"
    assert env["SESSION_EDGE_INITIAL_BALANCE"] == "100000.0"
    assert env["SESSION_EDGE_FTMO_PROFILE_VERIFIED"] == "true"
    assert env["SESSION_EDGE_ENABLED_SESSIONS"] == "LONDON"
    assert env["SESSION_EDGE_OVERLAP_MODE"] == "ALLOW"
    assert env["SESSION_EDGE_CALENDAR_ENABLED"] == "true"
    assert env["SESSION_EDGE_CALENDAR_PROVIDER"] == "forexfactory"
    assert env["SESSION_EDGE_CALENDAR_OUTPUT_FILE"] == env["SESSION_EDGE_NEWS_FILE"]


def test_build_env_drops_stale_config_and_preserves_base():
    env = _env()
    assert "SESSION_EDGE_CONFIG" not in env      # a stale config file must not override discovery
    assert env["PATH"] == "x"                    # base env preserved


def test_build_env_generated_config_loads_and_validates():
    """The env the launcher generates must satisfy the production config loader."""
    from forex_swing_orb.runtime.config import load_config
    env = _env()
    cfg = load_config(env=env)                   # must not raise
    assert cfg.bridge_root.endswith("session_edge_bridge")
    assert cfg.symbols == ("EURUSD.FX", "GBPUSD.FX")
    assert cfg.ftmo_profile_verified is True
    assert cfg.account_currency == "USD"
    assert cfg.initial_balance == 100000.0


def test_build_env_forex_only_rejected_by_config():
    """A non-Forex symbol still fails closed downstream (launcher can't bypass it)."""
    from forex_swing_orb.runtime.config import load_config, ConfigError
    env = _env(symbols=("AAPL.FX",))
    try:
        load_config(env=env)
        raised = False
    except ConfigError:
        raised = True
    assert raised


def test_launcher_has_no_direct_trade_authority():
    src = (Path(__file__).resolve().parents[1] / "launcher.py").read_text()
    for token in ("order_send", "order_check", "position_close", "PositionModify",
                  "modify_stop", "CTrade", ".Buy(", ".Sell(", "write_instruction"):
        assert token not in src, f"launcher must not contain {token}"


def test_children_are_the_accepted_entry_points():
    assert L.CHILDREN == ("forex_swing_orb.newsfeed", "forex_swing_orb.producer",
                          "forex_swing_orb.manage")


def test_canonical_symbols_normalizes():
    assert L.canonical_symbols(["EURUSD", "gbpusd", " usdjpy "]) == \
        ("EURUSD.FX", "GBPUSD.FX", "USDJPY.FX")
    assert L.canonical_symbols(["EURUSD.FX"]) == ("EURUSD.FX",)   # already canonical
    assert L.canonical_symbols(["", "  "]) == ()                  # blanks dropped
