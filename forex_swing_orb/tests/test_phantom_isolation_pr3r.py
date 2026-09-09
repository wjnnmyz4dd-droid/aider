"""PR-3R — enforce the Session Edge ⟂ Phantom isolation contract.

Phantom (`phantom/`, `phantom_institutional.py`) is a SEPARATE, pre-existing system that
shares this repository with Session Edge (`forex_swing_orb/`). These tests prove — from
the actual source tree, without importing phantom — that Session Edge cannot reach it as
a live authority and that the two systems do not collide on imports, launchers, env
vars, or the filesystem bridge protocol. See docs/SESSION_EDGE_PHANTOM_SEPARATION.md.

Read-only static checks (no phantom import; no trading behavior touched).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]           # /…/ (repo root)
SE = REPO / "forex_swing_orb"                         # Session Edge package
PHANTOM_DIR = REPO / "phantom"
PHANTOM_MONO = REPO / "phantom_institutional.py"


def _se_production_pyfiles():
    return [p for p in SE.rglob("*.py") if "/tests/" not in str(p) and "__pycache__" not in str(p)]


def test_session_edge_production_never_imports_phantom():
    """No forex_swing_orb production module imports phantom / phantom_institutional."""
    imp = re.compile(r"^\s*(?:import|from)\s+phantom(?:_institutional)?\b", re.M)
    offenders = [str(p.relative_to(REPO)) for p in _se_production_pyfiles() if imp.search(p.read_text())]
    assert offenders == [], f"Session Edge imports phantom in: {offenders}"


def test_session_edge_launchers_do_not_reference_phantom():
    """The Session Edge deployment path never mentions phantom (run_demo.py is Phantom's,
    deliberately NOT a Session Edge launcher, so it is excluded)."""
    launchers = [REPO / "run_session_edge.bat", REPO / "autostart_run.bat",
                 SE / "runtime" / "launcher.py"]
    for f in launchers:
        assert f.exists(), f"missing launcher {f}"
        assert "phantom" not in f.read_text().lower(), f"{f.name} references phantom"


def test_phantom_has_no_session_edge_env_or_bridge_paths():
    """Phantom references no SESSION_EDGE_* env var and none of Session Edge's bridge /
    run_dir / MemoryStore protocol paths (no filesystem-protocol collision)."""
    banned = ("SESSION_EDGE_", "session_edge_bridge", "forex_swing_orb")
    files = [p for p in PHANTOM_DIR.rglob("*.py") if "__pycache__" not in str(p)]
    if PHANTOM_MONO.exists():
        files.append(PHANTOM_MONO)
    for p in files:
        txt = p.read_text(errors="ignore")
        for b in banned:
            assert b not in txt, f"{p.relative_to(REPO)} references Session Edge token {b!r}"


def test_env_var_namespaces_are_disjoint():
    """Session Edge uses only SESSION_EDGE_* env; it never reads phantom's env keys."""
    phantom_keys = ("PHANTOM_", "TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    for p in _se_production_pyfiles():
        txt = p.read_text()
        for k in phantom_keys:
            assert k not in txt, f"Session Edge {p.relative_to(REPO)} reads phantom env {k!r}"


def test_sole_reachable_lot_size_authority_is_pr3j():
    """allowable_volume is defined once inside Session Edge (compliance/sizing.py). Any
    phantom sizing lives OUTSIDE forex_swing_orb and is therefore unreachable — separate,
    not a live duplicate."""
    owners = [str(p.relative_to(REPO)) for p in SE.rglob("*.py")
              if "/tests/" not in str(p) and re.search(r"^def allowable_volume\(", p.read_text(), re.M)]
    assert owners == ["forex_swing_orb/compliance/sizing.py"], owners


def test_phantom_has_no_broker_order_execution():
    """Phantom cannot place/modify/close broker orders (no MT5 execution path), so even
    if run it cannot trade. Guards the 'no execution capability' finding."""
    exec_tokens = re.compile(r"\border_send\b|\bOrderSend\b|MetaTrader5|mt5\.order|positions_get")
    files = [p for p in PHANTOM_DIR.rglob("*.py") if "__pycache__" not in str(p)]
    if PHANTOM_MONO.exists():
        files.append(PHANTOM_MONO)
    offenders = [str(p.relative_to(REPO)) for p in files if exec_tokens.search(p.read_text(errors="ignore"))]
    assert offenders == [], f"phantom appears to have broker execution in: {offenders}"


def test_separation_docs_present():
    """The separation is documented (notice inside phantom + Session Edge-side audit)."""
    assert (PHANTOM_DIR / "SEPARATE_SYSTEM.md").exists()
    assert (REPO / "docs" / "SESSION_EDGE_PHANTOM_SEPARATION.md").exists()
