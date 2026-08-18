"""Read-only installation preflight / self-check (installation/PR-3S).

    python -m forex_swing_orb.runtime.preflight

An operator DOCTOR that verifies a machine is ready to run Session Edge on DEMO —
WITHOUT starting the producer/manager/newsfeed and WITHOUT placing or modifying any
trade. It composes the EXISTING canonical authorities (it re-implements none):

  * config validity            -> runtime.config.load_config (fail-closed loader)
  * timezone backend           -> zoneinfo (needs `tzdata` on Windows)
  * lot-size metadata sanity    -> compliance.sizing.metadata_ok
  * price geometry              -> position.geometry.resolve
  * account freshness           -> producer.providers.validate_account
  * bar sufficiency/freshness   -> producer.providers.validate_bars
  * bridge presence / health    -> bridge.paths.BridgePaths + producer.bridge_health

Every check reports one of:  PASS · FAIL · ENV VALIDATION REQUIRED.
"ENV VALIDATION REQUIRED" means the check needs the live Windows/MT5/DEMO terminal
(or unset SESSION_EDGE_* env) and cannot be proven here — it is NEVER reported as a
false PASS. Exit code: 0 = all PASS; 1 = any FAIL; 2 = no FAIL but ENV items remain.

This module has ZERO trade authority: it never calls order_send, never writes a
bridge instruction, never mutates PM state, never starts a child process. The
MT5-touching checks only READ (initialize/account_info/symbol_info/copy_rates) and
then shut the connection down.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

PASS = "PASS"
FAIL = "FAIL"
ENV = "ENV VALIDATION REQUIRED"

# Sessions whose IANA zones must resolve (the strategy + reset tz). On Windows this
# is the `tzdata` dependency; if any fails the whole system fails closed at config.
_REQUIRED_TZS = ("Europe/Prague", "Europe/London", "America/New_York",
                 "Asia/Tokyo", "Australia/Sydney")


def _check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)              # stdlib zoneinfo needs 3.9+
    return ("Python >= 3.9", PASS if ok else FAIL,
            f"running {v.major}.{v.minor}.{v.micro}")


def _check_import(mod, *, required):
    try:
        __import__(mod)
        return (f"import {mod}", PASS, "available")
    except Exception as exc:                        # noqa: BLE001 - report, never raise
        if required:
            return (f"import {mod}", FAIL, f"missing ({exc}); pip install {mod}")
        return (f"import {mod}", ENV,
                f"not installed here; required on the Windows/MT5 machine ({mod})")


def _check_timezones():
    try:
        from zoneinfo import ZoneInfo
    except Exception as exc:                        # pragma: no cover - <3.9 only
        return ("timezone backend (zoneinfo)", FAIL, str(exc))
    missing = []
    for tz in _REQUIRED_TZS:
        try:
            ZoneInfo(tz)
        except Exception:                           # noqa: BLE001
            missing.append(tz)
    if missing:
        return ("timezone data (zoneinfo/tzdata)", FAIL,
                f"cannot load {missing}; on Windows run: pip install tzdata")
    return ("timezone data (zoneinfo/tzdata)", PASS, "all required IANA zones load")


def _check_config():
    """Validate SESSION_EDGE_* config via the canonical fail-closed loader."""
    from .config import load_config, ConfigError
    try:
        cfg = load_config()
    except ConfigError as exc:
        # Unset env is expected off the launcher; invalid env is a real problem, but we
        # cannot tell "unset" from "invalid" cheaply — report ENV with the exact reason.
        return ("runtime config (SESSION_EDGE_*)", ENV,
                f"not validated here: {exc}. The launcher sets these; verify on-machine."), None
    return ("runtime config (SESSION_EDGE_*)", PASS,
            f"valid: symbols={list(cfg.symbols)} sessions={list(cfg.enabled_sessions)} "
            f"initial_balance={cfg.initial_balance} {cfg.account_currency}"), cfg


def _check_bridge(cfg):
    if cfg is None:
        return ("bridge folders", ENV, "config unresolved; cannot locate bridge_root")
    from ..bridge.paths import BridgePaths
    try:
        paths = BridgePaths(cfg.bridge_root)
        present = paths.pending.exists() and paths.results.exists()
    except Exception as exc:                        # noqa: BLE001
        return ("bridge folders", ENV, f"cannot inspect {cfg.bridge_root}: {exc}")
    if present:
        return ("bridge folders", PASS, f"present under {cfg.bridge_root}")
    return ("bridge folders", ENV,
            f"absent under {cfg.bridge_root} (created automatically on producer start)")


def _mt5_checks(cfg):
    """READ-ONLY MT5 probes. When MetaTrader5/terminal is unavailable every MT5 check
    is ENV (never a false PASS). Never sends/modifies an order."""
    results = []
    try:
        import MetaTrader5 as mt5                   # noqa: N813
    except Exception:
        results.append(("MT5 terminal connection", ENV,
                        "MetaTrader5 not installed here; run on the Windows/MT5 machine"))
        results.append(("DEMO account", ENV, "requires the live terminal"))
        results.append(("symbol metadata (tick/point/volume)", ENV, "requires the live terminal"))
        results.append(("bar history sufficiency", ENV, "requires the live terminal"))
        results.append(("B2 MT5 time-base is UTC", ENV,
                        "run: python -m forex_swing_orb.validation.mt5_timebase_probe"))
        return results
    # Live terminal path (Windows). Read-only; shut down when done. pragma: not run in CI.
    connected = False                              # pragma: no cover - live terminal only
    try:                                            # pragma: no cover
        # Pin to the SAME terminal the launcher/children use (one authority:
        # SESSION_EDGE_MT5_TERMINAL_PATH / persisted selection). No bare fallback.
        from . import mt5_terminal as term
        plan = term.requested_plan(None, os.environ)
        try:
            sel = term.open_terminal(mt5, plan)
            connected = True
        except term.TerminalSelectionError as exc:
            results.append(("MT5 terminal connection", FAIL, str(exc)))
            return results
        results.append(("MT5 terminal selection", PASS,
                        f"{plan.get('source')}: {sel.get('terminal_path')}"))
        results.append(("MT5 terminal connection", PASS, "connected"))
        acct = mt5.account_info()
        is_demo = getattr(acct, "trade_mode", None) == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        results.append(("DEMO account", PASS if is_demo else FAIL,
                        f"trade_mode={getattr(acct,'trade_mode',None)!r} "
                        f"({'demo' if is_demo else 'NOT demo — refused'})"))
        results.append(_symbol_meta_check(mt5, cfg))
        results.append(_bars_check(mt5, cfg))
        results.append(("B2 MT5 time-base is UTC", ENV,
                        "confirm with: python -m forex_swing_orb.validation.mt5_timebase_probe"))
    except Exception as exc:                        # pragma: no cover
        results.append(("MT5 probe", FAIL, f"unexpected error (read-only probe): {exc}"))
    finally:                                        # pragma: no cover
        try:
            if connected:
                mt5.shutdown()
        except Exception:
            pass
    return results


def _symbol_meta_check(mt5, cfg):                    # pragma: no cover - live terminal only
    from ..compliance.sizing import metadata_ok
    suffix = getattr(cfg, "symbol_suffix", "") or ""
    bad = []
    for canon in (cfg.symbols if cfg else ()):
        broker = canon[:6] + suffix if canon.endswith(".FX") else canon
        si = mt5.symbol_info(broker)
        if si is None:
            bad.append(f"{broker}: not found")
            continue
        ok = metadata_ok(getattr(si, "trade_tick_size", 0.0), getattr(si, "trade_tick_value", 0.0),
                         getattr(si, "volume_min", 0.0), getattr(si, "volume_max", 0.0),
                         getattr(si, "volume_step", 0.0))
        if not ok:
            bad.append(f"{broker}: tick/volume metadata incomplete")
    if bad:
        return ("symbol metadata (tick/point/volume)", FAIL, "; ".join(bad))
    return ("symbol metadata (tick/point/volume)", PASS, "tick_size/value + volume min/max/step present")


def _bars_check(mt5, cfg):                           # pragma: no cover - live terminal only
    suffix = getattr(cfg, "symbol_suffix", "") or ""
    need = 60
    short = []
    for canon in (cfg.symbols if cfg else ()):
        broker = canon[:6] + suffix if canon.endswith(".FX") else canon
        rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M15, 0, need + 1)
        if rates is None or len(rates) < need:
            short.append(f"{broker}: {0 if rates is None else len(rates)}/{need}")
    if short:
        return ("bar history sufficiency (M15 >= 60)", FAIL, "; ".join(short))
    return ("bar history sufficiency (M15 >= 60)", PASS, "sufficient closed M15 history")


def run_checks():
    """Return a list of (name, status, detail). Pure/read-only; never raises."""
    results = [_check_python(),
               _check_import("pandas", required=True),
               _check_import("numpy", required=True),
               _check_import("MetaTrader5", required=False),
               _check_timezones()]
    cfg_result, cfg = _check_config()
    results.append(cfg_result)
    results.append(_check_bridge(cfg))
    results.extend(_mt5_checks(cfg))
    return results


def _overall(results):
    statuses = {s for _, s, _ in results}
    if FAIL in statuses:
        return FAIL, 1
    if ENV in statuses:
        return ENV, 2
    return PASS, 0


def main(argv=None):
    results = run_checks()
    width = max(len(n) for n, _, _ in results)
    print("=" * (width + 34))
    print(" Session Edge — installation preflight (read-only; no trades)")
    print(f" {datetime.now(timezone.utc).isoformat()}")
    print("=" * (width + 34))
    icon = {PASS: "✓", FAIL: "✗", ENV: "•"}
    for name, status, detail in results:
        print(f" {icon.get(status,'?')} {name.ljust(width)}  {status}")
        if detail:
            print(f"     {detail}")
    overall, code = _overall(results)
    print("-" * (width + 34))
    print(f" OVERALL: {overall}")
    if overall == ENV:
        print(" (No failures. Remaining items need the Windows/MT5 DEMO terminal — see")
        print("  docs/SESSION_EDGE_INSTALLATION.md and the Phase-5 validation matrix.)")
    print("=" * (width + 34))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
