"""MT5 terminal-mismatch fix: deterministically bind every Session Edge Python process
to ONE MT5 terminal so Python and the EA share the SAME MQL5\\Files\\session_edge_bridge.

Covers the 12 required cases with a fake MetaTrader5 module (no real terminal). Proves
single-terminal selection, no silent fallback, launcher/children/preflight identical
binding, bridge derivation from the selected terminal, and that capital/PR-3J/compliance
authorities are untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.runtime import mt5_terminal as T
from forex_swing_orb.runtime import launcher as L
from forex_swing_orb.runtime import config as CFG

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"


class _TI:
    def __init__(self, path, data_path):
        self.path, self.data_path = path, data_path


class FakeMT5:
    """Minimal stand-in for the MetaTrader5 package."""
    def __init__(self, ok=True, ti=None):
        self._ok, self._ti, self.calls = ok, ti, []

    def initialize(self, **kw):
        self.calls.append(kw)
        return self._ok

    def terminal_info(self):
        return self._ti

    def last_error(self):
        return (1, "fake error")

    def shutdown(self):
        pass


# 1. one MT5 installation -> discover (bare) works
def test_1_single_install_discover():
    m = FakeMT5(ok=True, ti=_TI(r"C:\MT5", r"C:\MT5\data"))
    sel = T.open_terminal(m, T.plan_terminal(None, None, None))
    assert m.calls == [{}] and sel["data_path"] == r"C:\MT5\data" and sel["source"] == "discover"


# 2. multiple installs -> operator pins via env; resolver selects it deterministically
def test_2_multiple_installs_env_pin_is_deterministic():
    env = {T.TERMINAL_ENV: r"C:\MT5-B\terminal64.exe"}
    plan = T.requested_plan(None, env=env, store_path=Path("/nonexistent/x.json"))
    assert plan == {"requested": r"C:\MT5-B\terminal64.exe", "source": "env", "verify_required": True}
    m = FakeMT5(ok=True, ti=_TI(r"C:\MT5-B", r"C:\MT5-B\data"))
    sel = T.open_terminal(m, plan)
    assert m.calls == [{"path": r"C:\MT5-B\terminal64.exe"}] and sel["data_path"] == r"C:\MT5-B\data"


# 3. explicit --mt5-terminal-path wins over env + persisted
def test_3_explicit_path_precedence():
    p = T.plan_terminal(r"C:\CLI\terminal64.exe", r"C:\ENV\terminal64.exe", r"C:\OLD\terminal64.exe")
    assert p["requested"] == r"C:\CLI\terminal64.exe" and p["source"] == "cli"


# 4. invalid terminal path -> fail closed
def test_4_invalid_terminal_path_fails_closed():
    m = FakeMT5(ok=False, ti=None)
    import pytest
    with pytest.raises(T.TerminalSelectionError):
        T.open_terminal(m, T.plan_terminal(r"C:\bad\terminal64.exe", None, None))


# 5. no silent fallback: a failed configured path never triggers a bare initialize
def test_5_no_silent_fallback():
    m = FakeMT5(ok=False, ti=None)
    import pytest
    with pytest.raises(T.TerminalSelectionError):
        T.open_terminal(m, T.plan_terminal(r"C:\bad\terminal64.exe", None, None))
    assert m.calls == [{"path": r"C:\bad\terminal64.exe"}]        # exactly one call, WITH path


# 6. launcher and children receive the identical terminal path (via build_env -> config)
def test_6_launcher_and_children_identical_terminal():
    exe = r"C:\MT5\terminal64.exe"
    env = L.build_env(
        {}, bridge_root="B", runtime_dir="R", news_file="N", symbols=("EURUSD.FX",),
        symbol_suffix="", initial_balance=50000.0, account_currency="USD",
        ftmo_source="s", ftmo_verified_at="2026-08-10", terminal_path=exe)
    assert env["SESSION_EDGE_MT5_TERMINAL_PATH"] == exe
    cfg = CFG.load_config(env=env)                                # what the children load
    assert cfg.mt5_terminal_path == exe                          # wiring forwards this to initialize(path=)
    # without a terminal_path the key is simply absent (unchanged default behavior)
    env0 = L.build_env(
        {}, bridge_root="B", runtime_dir="R", news_file="N", symbols=("EURUSD.FX",),
        symbol_suffix="", initial_balance=50000.0, account_currency="USD",
        ftmo_source="s", ftmo_verified_at="2026-08-10")
    assert "SESSION_EDGE_MT5_TERMINAL_PATH" not in env0


# 7. preflight uses the SAME resolver (identical terminal selection)
def test_7_preflight_uses_same_terminal_resolver():
    src = (PKG / "runtime" / "preflight.py").read_text()
    assert "mt5_terminal" in src and "requested_plan" in src and "open_terminal" in src
    # both sides resolve from the same env authority
    env = {T.TERMINAL_ENV: r"C:\MT5\terminal64.exe"}
    assert T.requested_plan(None, env=env, store_path=Path("/nonexistent"))["requested"] \
        == r"C:\MT5\terminal64.exe"


# 8. bridge path derives from the SELECTED terminal's data_path
def test_8_bridge_path_from_selected_terminal():
    m = FakeMT5(ok=True, ti=_TI(r"C:\MT5", r"C:\Users\t\AppData\Roaming\MetaQuotes\Terminal\ABC"))
    sel = T.open_terminal(m, T.plan_terminal(None, None, None))
    bridge = L.bridge_root_from_data_path(sel["data_path"])
    assert bridge == str(Path(sel["data_path"]) / "MQL5" / "Files" / "session_edge_bridge")


# 9. EA-expected vs Python path are comparable deterministically
def test_9_python_and_ea_paths_comparable():
    data = r"C:\Users\t\AppData\Roaming\MetaQuotes\Terminal\ABC"
    python_bridge = L.bridge_root_from_data_path(data)
    ea_expected = str(Path(data) / "MQL5" / "Files" / "session_edge_bridge")   # EA default settings
    assert T.paths_equal(python_bridge, ea_expected)
    assert not T.paths_equal(python_bridge,
                             L.bridge_root_from_data_path(r"C:\Other\Terminal\XYZ"))


# 10. capital-base persistence is unchanged (separate owner; no coupling)
def test_10_capital_layer_unchanged():
    from forex_swing_orb.runtime import capital as C
    src = (PKG / "runtime" / "capital.py").read_text()
    assert "mt5_terminal" not in src                             # capital doesn't depend on this fix
    # capital store still resolves as before
    import tempfile
    s = C.CapitalBaseStore(Path(tempfile.mkdtemp()) / "capital_base.json")
    r = C.resolve_capital_base(s, login=1, server="X", currency="USD",
                               current_balance=100000.0, cli_initial=None,
                               reinitialize=None, now_iso="t")
    assert r.ok and r.initial_balance == 100000.0


# 11. PR-3J / compliance / execution semantics unchanged
def test_11_risk_execution_unchanged():
    owners = [str(p.relative_to(REPO)) for p in PKG.rglob("*.py")
              if "/tests/" not in str(p) and re.search(r"^def allowable_volume\(", p.read_text(), re.M)]
    assert owners == ["forex_swing_orb/compliance/sizing.py"]
    assert "return initial * rf" in (PKG / "compliance" / "contract.py").read_text()
    # the terminal fix touches no strategy/compliance/sizing/execution source
    # (no IMPORT of the new module there; substring 'mt5_terminal_id' ack field is unrelated)
    for changed in ("compliance/sizing.py", "compliance/contract.py",
                    "run_dir/code/signal_engine.py", "ea_mt5/execution_consumer.py"):
        assert not re.search(r"import\s+mt5_terminal|from\s+\S*\s+import\s+.*mt5_terminal",
                             (PKG / changed).read_text())


# 12. no duplicate terminal / bridge authority
def test_12_single_terminal_and_bridge_authority():
    # ONE terminal env authority — reuses the existing config key name
    assert T.TERMINAL_ENV == CFG._ENV["mt5_terminal_path"]
    # bridge_root_from_data_path defined once (launcher)
    owners = [str(p.relative_to(REPO)) for p in PKG.rglob("*.py")
              if "/tests/" not in str(p) and re.search(r"^def bridge_root_from_data_path\(", p.read_text(), re.M)]
    assert owners == ["forex_swing_orb/runtime/launcher.py"]
    # mt5_terminal does not define its own bridge-path function
    assert "def bridge_root" not in (PKG / "runtime" / "mt5_terminal.py").read_text()


# persistence round-trip + fail-closed cache
def test_persist_load_roundtrip_and_malformed(tmp_path):
    sp = tmp_path / ".session_edge" / "terminal.json"
    T.persist(sp, r"C:\MT5\terminal64.exe", r"C:\MT5\data", "t")
    assert T.load_persisted(sp) == r"C:\MT5\terminal64.exe"
    bad = tmp_path / "bad.json"; bad.write_text("{ not json", encoding="utf-8")
    assert T.load_persisted(bad) is None                        # corrupt cache -> re-discover
    assert T.load_persisted(tmp_path / "missing.json") is None
