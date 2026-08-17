"""PR-3A H3: the launcher pins the FTMO initial balance to the operator-attested
value and NEVER re-anchors it to the current live account balance on restart.
Deterministic; no MT5."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.runtime import launcher as L                            # noqa: E402


def test_initial_pinned_after_drawdown():
    # true challenge initial 50000, live balance drawn down to 47000
    assert L.resolve_initial_balance(50000, live_balance=47000) == 50000.0


def test_initial_pinned_after_profit():
    assert L.resolve_initial_balance(50000, live_balance=52000) == 50000.0


def test_missing_initial_fails_closed_never_uses_live():
    assert L.resolve_initial_balance(None, live_balance=47000) is None
    assert L.resolve_initial_balance(None, live_balance=999999) is None


def test_invalid_initial_fails_closed():
    assert L.resolve_initial_balance(0, live_balance=50000) is None
    assert L.resolve_initial_balance(-5, live_balance=50000) is None
    assert L.resolve_initial_balance("abc", live_balance=50000) is None


def test_build_env_uses_pinned_initial_not_live():
    env = L.build_env(
        {}, bridge_root="B", runtime_dir="R", news_file="N",
        symbols=("EURUSD.FX",), symbol_suffix="", initial_balance=50000.0,
        account_currency="USD", ftmo_source="s", ftmo_verified_at="2026-08-10")
    assert env["SESSION_EDGE_INITIAL_BALANCE"] == "50000.0"


def test_autostart_bat_has_no_usable_default_initial_balance():
    # P3A-2 (updated for zero-friction startup): the autostart wrapper still carries NO
    # executable numeric default. When INITIAL_BALANCE is left blank the launcher
    # auto-captures + PINS the current DEMO balance ONCE (runtime.capital) and reuses
    # that pinned value on every restart (H3 preserved by persistence, not re-entry);
    # the wrapper passes --initial-balance ONLY when the operator explicitly set one.
    txt = (REPO_ROOT / "autostart_run.bat").read_text()
    assert "set INITIAL_BALANCE=50000" not in txt        # no guessed default
    assert 'set "INITIAL_BALANCE="' in txt               # empty by default
    assert 'if "%INITIAL_BALANCE%"==""' in txt           # blank -> auto-capture branch
    assert "--initial-balance %INITIAL_BALANCE%" in txt  # explicit value only when set


def test_config_loads_with_pinned_initial():
    from forex_swing_orb.runtime.config import load_config
    env = L.build_env(
        {}, bridge_root="B", runtime_dir="R", news_file="N",
        symbols=("EURUSD.FX",), symbol_suffix="", initial_balance=50000.0,
        account_currency="USD", ftmo_source="s", ftmo_verified_at="2026-08-10")
    cfg = load_config(env=env)
    assert cfg.initial_balance == 50000.0
