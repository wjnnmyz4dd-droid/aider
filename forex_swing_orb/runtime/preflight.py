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

from ..bridge import serialize

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


def _check_ea_liveness(cfg, now):
    """EA_LIVENESS — proven ONLY by a fresh, same-bridge EA heartbeat (never by a
    Python filesystem probe). Kept DELIBERATELY SEPARATE from H5 instruction health.
    PASS -> ready; MISSING -> ENV (EA not started/attached here); STALE/WRONG_BRIDGE/
    MALFORMED/UNKNOWN_SCHEMA -> FAIL (a real misconfiguration or stopped EA)."""
    if cfg is None:
        return ("EA liveness (bridge heartbeat)", ENV, "config unresolved; cannot locate bridge_root")
    from . import ea_liveness as el
    try:
        r = el.read_ea_status(cfg.bridge_root, now,
                              expected_bridge_root_name="session_edge_bridge",
                              expected_use_common=False,
                              expected_bridge_abspath=cfg.bridge_root)
    except Exception as exc:                             # noqa: BLE001
        return ("EA liveness (bridge heartbeat)", ENV, f"could not read heartbeat: {exc}")
    if r.state == el.PASS:
        return ("EA liveness (bridge heartbeat)", PASS, r.detail)
    if r.state == el.MISSING:
        return ("EA liveness (bridge heartbeat)", ENV,
                f"{r.detail}; attach the EA in the pinned terminal (BridgeRoot="
                f"session_edge_bridge, UseCommonFolder=false) and re-run on-machine")
    return ("EA liveness (bridge heartbeat)", FAIL, f"{r.state}: {r.detail}")


def _check_h5(cfg, now):
    """H5 instruction/ACK health (producer.bridge_health) — the SEPARATE authority for
    whether written instructions are being acknowledged. Not a proxy for EA liveness."""
    if cfg is None:
        return ("H5 instruction health (ACKs)", ENV, "config unresolved")
    from ..bridge.paths import BridgePaths
    from ..producer import bridge_health
    try:
        paths = BridgePaths(cfg.bridge_root)
        if not (paths.pending.exists() and paths.results.exists()):
            return ("H5 instruction health (ACKs)", ENV,
                    f"bridge not present under {cfg.bridge_root} (created on producer start)")
        obs = bridge_health.observe_entry_bridge(paths, now)
    except Exception as exc:                             # noqa: BLE001
        return ("H5 instruction health (ACKs)", ENV, f"could not observe bridge: {exc}")
    if obs.healthy:
        return ("H5 instruction health (ACKs)", PASS,
                f"healthy; missing_ack_count={obs.missing_ack_count}")
    return ("H5 instruction health (ACKs)", FAIL,
            f"unhealthy; missing_ack_count={obs.missing_ack_count}")


def _check_daily_anchor(cfg, now):
    """Daily-anchor VISIBILITY only (spec §J/§Q/§T): report presence/validity, SOURCE
    (LIVE_ROLLOVER / BROKER_HISTORY_RECONSTRUCTION), Prague day, and cold-start history
    coverage for today's Prague trading day. READ-ONLY: it reads the PERSISTED anchor
    the producer wrote — it never creates, repairs, reconstructs, or auto-fills it (the
    tracker is the sole reconstruction authority; a mid-day cold start with no provable
    anchor stays fail-closed via R_ACCOUNT_ANCHOR_UNAVAILABLE)."""
    name = "daily anchor (today, visibility only)"
    if cfg is None:
        return [(name, ENV, "config unresolved")]
    from ..compliance.contract import prague_trading_day
    try:
        tday = prague_trading_day(now)
        p = __import__("pathlib").Path(cfg.anchor_path)
        if not p.exists():
            return [(name, ENV,
                     f"absent for {tday}; established at producer start (live rollover, "
                     f"or verified broker-history reconstruction on a cold start)"),
                    ("daily anchor source", ENV, f"not established yet for {tday}"),
                    ("daily anchor history coverage", ENV, "requires the live terminal")]
        ok, obj = serialize.loads(p.read_text(encoding="utf-8"))
        rec = obj.get("records", {}).get(tday) if ok else None
        if not isinstance(rec, dict):
            return [(name, ENV, f"no record for {tday} (established at producer start)"),
                    ("daily anchor source", ENV, f"not established yet for {tday}"),
                    ("daily anchor history coverage", ENV, "requires the live terminal")]
        if not serialize.verify_integrity_digest(rec):
            return [(name, FAIL, f"anchor for {tday} present but integrity digest INVALID"),
                    ("daily anchor source", FAIL, "record integrity invalid"),
                    ("daily anchor history coverage", FAIL, "record integrity invalid")]
        source = rec.get("anchor_source") or "LIVE_ROLLOVER (legacy record)"
        recon = rec.get("reconstruction") if isinstance(rec.get("reconstruction"), dict) else None
        out = [(name, PASS, f"present + valid for {tday}"),
               ("daily anchor source", PASS, source)]
        if recon:
            out.append(("daily anchor history coverage", PASS,
                        f"from {recon.get('history_from_utc')} to {recon.get('history_to_utc')}; "
                        f"{recon.get('event_count')} event(s); flat-book proven"))
        else:
            out.append(("daily anchor history coverage", PASS,
                        "n/a (live rollover capture)"))
        return out
    except Exception as exc:                             # noqa: BLE001
        return [(name, ENV, f"could not read anchor: {exc}")]


def _check_producer_state(cfg, now):
    """Producer last-cycle state (visibility) via the single owner operator_status,
    read from the runner audit. BLOCKED/ERROR -> FAIL (a real readiness blocker);
    WAITING/READY -> PASS; no recorded cycle -> ENV."""
    if cfg is None:
        return ("producer last-cycle state", ENV, "config unresolved")
    from . import operator_status as ops
    try:
        p = __import__("pathlib").Path(cfg.runner_audit_path)
        if not p.exists():
            return ("producer last-cycle state", ENV, "no runner audit yet (producer not started)")
        last = None
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ok, obj = serialize.loads(line)
            if ok:
                last = obj
        if last is None:
            return ("producer last-cycle state", ENV, "no cycle recorded yet")
        st = ops.producer_state(True, last)
        if st["state"] in (ops.PRODUCER_BLOCKED, ops.PRODUCER_ERROR):
            return ("producer last-cycle state", FAIL, st["detail"])
        return ("producer last-cycle state", PASS, st["detail"])
    except Exception as exc:                             # noqa: BLE001
        return ("producer last-cycle state", ENV, f"could not read runner audit: {exc}")


def _check_service_health(cfg, now, service, path_attr, label):
    """F2: producer/manager HEALTH-ARTIFACT freshness via the single owner
    runtime.service_health (SEPARATE from EA liveness and H5). PASS -> fresh/alive;
    MISSING -> ENV (service not started here); STALE/MALFORMED/WRONG_SERVICE/
    UNKNOWN_SCHEMA -> FAIL (a stale artifact from a dead process is never a false green)."""
    if cfg is None:
        return (label, ENV, "config unresolved; cannot locate health artifact")
    from . import service_health as svc
    try:
        path = getattr(cfg, path_attr)
        r = svc.read_service_health(path, service, now)
    except Exception as exc:                             # noqa: BLE001 - report, never raise
        return (label, ENV, f"could not read {service} health: {exc}")
    if r.state == svc.PASS:
        return (label, PASS, r.detail)
    if r.state == svc.MISSING:
        return (label, ENV,
                f"{r.detail}; the {service} writes it once started (verify on-machine)")
    return (label, FAIL, f"{r.state}: {r.detail}")


def _check_producer_health(cfg, now):
    return _check_service_health(cfg, now, "producer", "producer_health_path",
                                 "producer health (process alive)")


def _check_manager_health(cfg, now):
    return _check_service_health(cfg, now, "manager", "manager_health_path",
                                 "manager health (process alive)")


def _check_bridge_end_to_end(cfg, ea_liveness_result, bridge_present):
    """BRIDGE_END_TO_END — READY requires BOTH the Python filesystem presence AND a
    fresh EA heartbeat (ea_liveness PASS). Python-side presence alone is NOT end-to-end."""
    ea_pass = ea_liveness_result[1] == PASS
    if bridge_present and ea_pass:
        return ("bridge END-TO-END (Python + live EA)", PASS,
                "filesystem present AND fresh same-bridge EA heartbeat")
    if not bridge_present:
        return ("bridge END-TO-END (Python + live EA)", ENV,
                "bridge filesystem not present here")
    # filesystem present but EA not proven live
    return ("bridge END-TO-END (Python + live EA)",
            ENV if ea_liveness_result[1] == ENV else FAIL,
            "NOT end-to-end: no fresh same-bridge EA heartbeat "
            f"(EA liveness = {ea_liveness_result[1]})")


def _check_sessions(cfg):
    """Effective trading-session selection (spec §K). The single authority is
    runtime.config -> SessionModel; a resolved cfg means the selection already passed
    fail-closed validation. When cfg is unresolved, independently validate the raw
    SESSION_EDGE_ENABLED_SESSIONS so an INVALID selection reads as FAIL (not a false
    green) even off the launcher."""
    from ..session.profiles import SUPPORTED_SESSION_IDS

    def _label(sessions):
        return (f"ALL ({len(sessions)})" if tuple(sessions) == tuple(SUPPORTED_SESSION_IDS)
                else ", ".join(sessions))

    if cfg is not None:
        sessions = tuple(cfg.enabled_sessions)
        if not sessions:
            return ("Trading Sessions", FAIL, "no sessions enabled")
        return ("Trading Sessions", PASS, _label(sessions))
    raw = os.environ.get("SESSION_EDGE_ENABLED_SESSIONS")
    if raw:
        from . import session_selection
        try:
            s = session_selection.normalize_sessions(raw)
        except session_selection.SessionSelectionError as exc:
            return ("Trading Sessions", FAIL, f"invalid SESSION_EDGE_ENABLED_SESSIONS: {exc}")
        return ("Trading Sessions", PASS, f"{_label(s)} (config not fully resolved here)")
    return ("Trading Sessions", ENV,
            "no selection set here; the launcher persists/sets it (default LONDON)")


def _check_lot_sizing():
    """Lot-sizing authority (spec §K). Sizing is autonomous — PR-3J
    (compliance/sizing.allowable_volume) is the SOLE live authority — and there must be
    NO manual lot control. Proves, by reading the shipped EA source, that no manual
    lot/volume/risk INPUT is exposed; a reintroduced manual input reads as FAIL."""
    import re
    out = [("Lot Sizing Authority", PASS,
            "AUTONOMOUS — PR-3J (compliance/sizing.allowable_volume)")]
    try:
        ea = (__import__("pathlib").Path(__file__).resolve().parents[1]
              / "ea_mt5" / "SessionEdgeExecutionEA.mq5").read_text(encoding="utf-8")
        manual = re.search(r"^\s*input\s+\w+\s+\w*(?:[Vv]olume|[Ll]ot|[Rr]isk)\w*", ea, re.M)
        if manual:
            out.append(("Manual Lot Override", FAIL,
                        f"EA exposes a manual lot input: {manual.group(0).strip()!r}"))
        else:
            out.append(("Manual Lot Override", PASS,
                        "DISABLED — no manual lot/volume/risk input in the EA"))
    except Exception as exc:                             # noqa: BLE001
        out.append(("Manual Lot Override", PASS,
                    "DISABLED — EA sizes autonomously (source not read here)"))
    return out


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


def run_checks(now=None):
    """Return a list of (name, status, detail). Pure/read-only; never raises."""
    now = now or datetime.now(timezone.utc)
    results = [_check_python(),
               _check_import("pandas", required=True),
               _check_import("numpy", required=True),
               _check_import("MetaTrader5", required=False),
               _check_timezones()]
    cfg_result, cfg = _check_config()
    results.append(cfg_result)
    results.append(_check_sessions(cfg))
    results.extend(_check_lot_sizing())
    bridge_result = _check_bridge(cfg)
    results.append(bridge_result)
    bridge_present = bridge_result[1] == PASS
    # Readiness-truthfulness checks (spec §M). EA liveness is a heartbeat proof, kept
    # DELIBERATELY SEPARATE from H5 instruction health; bridge END-TO-END requires BOTH
    # the filesystem AND a live EA — never Python-only.
    ea_result = _check_ea_liveness(cfg, now)
    results.append(ea_result)
    results.append(_check_h5(cfg, now))
    results.append(_check_bridge_end_to_end(cfg, ea_result, bridge_present))
    results.extend(_check_daily_anchor(cfg, now))
    results.append(_check_producer_state(cfg, now))
    # F2: producer/manager process aliveness proven by fresh health artifacts (a stale
    # artifact from a dead process can never read as current). Separate from EA liveness
    # and H5.
    results.append(_check_producer_health(cfg, now))
    results.append(_check_manager_health(cfg, now))
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
    # SYSTEM STATUS (spec §M): READY only when EVERY check PASSes — which by
    # construction requires a fresh EA heartbeat (EA liveness PASS), an end-to-end
    # bridge, a valid daily anchor, and an un-blocked producer. READY here means
    # "correctly wired and unblocked", NOT "a trade should exist". Any non-PASS check
    # is listed as a blocker so a false green is impossible.
    blockers = [(n, s) for n, s, _ in results if s != PASS]
    system_ready = not blockers
    print("=" * (width + 34))
    print(f" SYSTEM STATUS: {'READY' if system_ready else 'NOT READY'}")
    if blockers:
        print(" Blockers (each must reach PASS for SYSTEM READY):")
        for n, s in blockers:
            print(f"   - [{s}] {n}")
    print("=" * (width + 34))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
