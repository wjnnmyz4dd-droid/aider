"""Canonical MT5 terminal selection — the ONE owner that binds every Session Edge
Python process (launcher, producer, manager, preflight) to the SAME MetaTrader 5
terminal, so they all resolve the SAME ``MQL5\\Files\\session_edge_bridge`` that the EA
reads.

Root cause this closes: bare ``MetaTrader5.initialize()`` (no path) selects a terminal
nondeterministically — with more than one MT5 installation it can attach Python to a
DIFFERENT terminal than the one running the EA (Python writes the bridge under terminal
A's Files; the EA looks under terminal B's Files → "bridge_root not found").

Single authority: the terminal executable path, carried by the EXISTING config key
``SESSION_EDGE_MT5_TERMINAL_PATH`` (``runtime.config.mt5_terminal_path``, already
forwarded to ``MetaTrader5.initialize(path=…)`` by ``runtime.wiring.build_client``). This
module only RESOLVES + VERIFIES + PERSISTS that one value; it introduces no second
terminal or bridge authority and changes no trading behavior. Bridge-path derivation
stays with ``launcher.bridge_root_from_data_path`` (fed this module's data_path).

Fails closed: a configured terminal that cannot be opened is NEVER silently replaced by
another installation, and a terminal that reports no data_path is refused.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text

# Reuse the existing env authority name (do NOT invent a second one).
TERMINAL_ENV = "SESSION_EDGE_MT5_TERMINAL_PATH"
SELECTION_SCHEMA_VERSION = 1

# Standard MetaTrader 5 executables inside a terminal installation directory.
_EXE_CANDIDATES = ("terminal64.exe", "terminal.exe")


class TerminalSelectionError(RuntimeError):
    """Raised when the pinned terminal cannot be opened/verified. Fail closed."""


def selection_store_path(home=None):
    """Stable, pre-connect persistence location (NOT under the terminal Files folder,
    which is unknown until we connect). One file, owned solely by this module."""
    base = Path(home) if home is not None else Path.home()
    return base / ".session_edge" / "terminal.json"


def load_persisted(store_path):
    """Return the persisted terminal executable path, or None. A missing/corrupt cache
    is treated as absent (the launcher re-discovers) — it is only a convenience cache,
    never a trading authority."""
    try:
        text = Path(store_path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    ok, obj = serialize.loads(text)
    if not ok or not isinstance(obj, dict):
        return None
    tp = obj.get("terminal_path")
    return str(tp) if tp else None


def persist(store_path, terminal_path, data_path, now_iso):
    """Atomically record the selected terminal (executable + data_path) for next run."""
    p = Path(store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, serialize.canonical_json({
        "schema_version": SELECTION_SCHEMA_VERSION,
        "terminal_path": terminal_path,
        "data_path": data_path,
        "saved_at": now_iso,
    }))
    return terminal_path


def plan_terminal(cli_path=None, env_path=None, persisted_path=None):
    """Decide which terminal to request. Precedence: explicit CLI > env
    (SESSION_EDGE_MT5_TERMINAL_PATH) > persisted selection > discover (no path).
    ``verify_required`` is True whenever a specific terminal was requested, so a
    failure to open it fails closed instead of falling back to another install."""
    for source, val in (("cli", cli_path), ("env", env_path), ("persisted", persisted_path)):
        if val:
            return {"requested": str(val), "source": source, "verify_required": True}
    return {"requested": None, "source": "discover", "verify_required": False}


def requested_plan(cli_path=None, env=None, store_path=None):
    """Build the plan from CLI + environment + persisted cache (single resolver used by
    both the launcher and preflight so they always agree)."""
    env = os.environ if env is None else env
    env_path = env.get(TERMINAL_ENV) or None
    persisted = load_persisted(store_path if store_path is not None else selection_store_path())
    return plan_terminal(cli_path, env_path, persisted)


def paths_equal(a, b):
    """OS-insensitive path comparison (Windows case/sep-insensitive)."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def resolve_exe(install_dir):
    """The terminal executable inside an install directory (terminal64.exe preferred),
    verified to exist. None if neither standard executable is present."""
    if not install_dir:
        return None
    base = Path(install_dir)
    for name in _EXE_CANDIDATES:
        cand = base / name
        try:
            if cand.exists():
                return str(cand)
        except OSError:
            continue
    return None


def open_terminal(mt5, plan):
    """Open the planned terminal on the injected ``mt5`` module (the real MetaTrader5
    package in production; a double in tests). Returns a dict with ``terminal_path``
    (install dir), ``data_path`` and ``source``. Fails closed:

      * a REQUESTED terminal that ``initialize(path=…)`` cannot open raises — it is NEVER
        silently replaced by a bare ``initialize()`` on another installation;
      * a connected terminal that reports no data_path raises (bridge unresolvable)."""
    requested = plan.get("requested")
    try:
        ok = mt5.initialize(path=requested) if requested else mt5.initialize()
    except Exception as exc:                            # noqa: BLE001
        raise TerminalSelectionError(f"MetaTrader5.initialize failed: {exc!r}")
    if not ok:
        le = ""
        try:
            le = f" (last_error={mt5.last_error()!r})"
        except Exception:                               # noqa: BLE001
            pass
        if requested:
            raise TerminalSelectionError(
                f"could not open the configured MT5 terminal at '{requested}'{le} — "
                f"refusing to fall back to another installation (fail closed).")
        raise TerminalSelectionError(f"MetaTrader5.initialize() could not attach to a terminal{le}.")
    ti = mt5.terminal_info()
    data_path = getattr(ti, "data_path", None) if ti is not None else None
    install_dir = getattr(ti, "path", None) if ti is not None else None
    if not data_path:
        try:
            mt5.shutdown()
        except Exception:                               # noqa: BLE001
            pass
        raise TerminalSelectionError(
            "connected terminal did not report a data_path; cannot resolve the bridge "
            "(fail closed).")
    return {"requested": requested, "source": plan.get("source"),
            "terminal_path": install_dir, "data_path": data_path}


def effective_terminal_exe(selection):
    """The executable path to propagate to child processes / persist, so every Python
    process pins the SAME terminal. Prefers the explicitly requested exe; otherwise
    derives it from the connected install directory. May be None if a discovered install
    exposes no standard executable (the launcher then warns that determinism needs an
    explicit --mt5-terminal-path / SESSION_EDGE_MT5_TERMINAL_PATH)."""
    return selection.get("requested") or resolve_exe(selection.get("terminal_path"))
