"""One-command automatic launcher for the DEMO-only Session Edge pipeline.

    python -m forex_swing_orb.runtime.launcher --ftmo-verified

Removes the manual multi-window setup: it attaches to the already-running MT5
terminal, auto-discovers the terminal Files folder + account currency/balance,
builds a validated configuration, and starts the three existing entry points
together — newsfeed (real economic calendar), producer, and manager — with a
single graceful shutdown.

It is ORCHESTRATION ONLY. It adds no trade authority, changes no strategy /
compliance / FTMO / bridge / EA / PM logic, and spawns the accepted
``python -m forex_swing_orb.{newsfeed,producer,manage}`` entry points unmodified.
Every existing fail-closed gate still applies in the children (invalid config,
unusable FTMO profile, non-demo account, stale news → the child refuses to run).

Two safety attestations are deliberately NOT auto-defaulted:
  * DEMO account — the launcher refuses to start on anything but a connected demo;
  * FTMO profile verification — the operator must attest once, via ``--ftmo-verified``
    or an interactive confirmation. The launcher never silently forces it true.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from ..live import mt5_client as mc
from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from . import capital
from . import mt5_terminal as term

DEFAULT_SYMBOLS = ("EURUSD.FX",)
DEFAULT_SESSIONS = ("LONDON",)
DEFAULT_OVERLAP_MODE = "ALLOW"
DEFAULT_PROVIDER = "forexfactory"
CHILDREN = ("forex_swing_orb.newsfeed", "forex_swing_orb.producer",
            "forex_swing_orb.manage")

REPO_ROOT = Path(__file__).resolve().parents[2]   # dir containing forex_swing_orb/


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested off-Windows)
# --------------------------------------------------------------------------- #
def bridge_root_from_data_path(data_path):
    """The EA's bridge root under the terminal data folder: MQL5\\Files\\session_edge_bridge."""
    return str(Path(data_path) / "MQL5" / "Files" / "session_edge_bridge")


def account_is_demo(trade_mode):
    """Only ACCOUNT_TRADE_MODE_DEMO is treated as demo (real/contest/unknown -> False)."""
    return trade_mode == mc.ACCOUNT_TRADE_MODE_DEMO


def canonical_symbols(symbols):
    """Normalize operator-friendly symbols to the config's canonical '<PAIR>.FX'
    form (e.g. 'eurusd' / 'EURUSD' -> 'EURUSD.FX'). Forex-majors validation still
    happens downstream in runtime.config (fail closed); this only reshapes."""
    out = []
    for s in symbols:
        s = str(s).strip().upper()
        if not s:
            continue
        if not s.endswith(".FX"):
            s = s + ".FX"
        out.append(s)
    return tuple(out)


def canonical_sessions(raw):
    """Normalize an operator ``--sessions`` value into a validated, deduplicated,
    canonically-ordered tuple. Delegates to the ONE session-selection normalizer
    (runtime.session_selection.normalize_sessions) so the launcher, persistence, and
    CLI cannot diverge. runtime.config remains the single session AUTHORITY (it
    re-validates, fail closed). Raises ValueError on an unknown/empty selection."""
    from . import session_selection
    return session_selection.normalize_sessions(raw)


def build_env(base_env, *, bridge_root, runtime_dir, news_file, symbols,
              symbol_suffix, initial_balance, account_currency, ftmo_source,
              ftmo_verified_at, enabled_sessions=DEFAULT_SESSIONS,
              overlap_mode=DEFAULT_OVERLAP_MODE, calendar_provider=DEFAULT_PROVIDER,
              terminal_path=None, risk_profile=None, risk_fraction=None,
              sizing_mode=None):
    """Build the child environment. FTMO_PROFILE_VERIFIED is set true here because
    the caller only reaches this step AFTER the operator has attested (see main).
    ``terminal_path`` (when known) pins producer/manager to the SAME MT5 terminal the
    launcher connected to (via the existing SESSION_EDGE_MT5_TERMINAL_PATH authority)."""
    env = dict(base_env)
    if terminal_path:
        env["SESSION_EDGE_MT5_TERMINAL_PATH"] = str(terminal_path)
    env.update({
        # producer / manager (consumed by runtime.config)
        "SESSION_EDGE_BRIDGE_ROOT": str(bridge_root),
        "SESSION_EDGE_RUNTIME_DIR": str(runtime_dir),
        "SESSION_EDGE_NEWS_FILE": str(news_file),
        "SESSION_EDGE_SYMBOLS": ",".join(symbols),
        "SESSION_EDGE_SYMBOL_SUFFIX": symbol_suffix or "",
        "SESSION_EDGE_INITIAL_BALANCE": str(float(initial_balance)),
        "SESSION_EDGE_ACCOUNT_CURRENCY": str(account_currency),
        "SESSION_EDGE_FTMO_RULE_SOURCE": ftmo_source,
        "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": ftmo_verified_at,
        "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
        "SESSION_EDGE_ENABLED_SESSIONS": ",".join(enabled_sessions),
        "SESSION_EDGE_OVERLAP_MODE": overlap_mode,
        # newsfeed (real-calendar acquisition, writing the same news_file)
        "SESSION_EDGE_CALENDAR_ENABLED": "true",
        "SESSION_EDGE_CALENDAR_PROVIDER": calendar_provider,
        "SESSION_EDGE_CALENDAR_OUTPUT_FILE": str(news_file),
    })
    # user risk configuration (front-end resolved; PR-3J stays the sole sizer)
    if risk_profile:
        env["SESSION_EDGE_RISK_PROFILE"] = str(risk_profile)
    if sizing_mode:
        env["SESSION_EDGE_SIZING_MODE"] = str(sizing_mode)
    if risk_fraction is not None:
        env["SESSION_EDGE_RISK_FRACTION"] = repr(float(risk_fraction))
    # a stale SESSION_EDGE_CONFIG file would override our env — drop it so discovery wins
    env.pop("SESSION_EDGE_CONFIG", None)
    return env


def resolve_initial_balance(cli_initial, live_balance=None):
    """H3: the FTMO initial balance (challenge starting capital) is the operator-
    attested value ONLY. It is NEVER derived from the live account balance — doing
    so would drift the static max-loss floor downward after any drawdown on every
    restart. Returns the pinned initial, or None (fail closed) when it is not
    explicitly provided or is invalid. ``live_balance`` is accepted purely to make
    explicit that it is deliberately IGNORED."""
    if cli_initial is None:
        return None
    try:
        v = float(cli_initial)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def attestation_ok(*, flag, tty_confirm=None):
    """The operator has attested the FTMO profile iff the flag was passed OR an
    interactive confirmation returned the exact word VERIFIED."""
    if flag:
        return True
    if tty_confirm is None:
        return False
    return str(tty_confirm).strip() == "VERIFIED"


def bridge_handshake(bridge_root, now_iso, *, use_common_folder=False):
    """Read-only-safe bridge self-check (no trade). Ensures the bridge tree the
    producer/EA share (the producer would create it anyway), then proves Python can
    write AND read back a diagnostic probe under ``health/`` — a directory the EA never
    claims (it only claims ``outbox/pending``), so this never looks like an instruction
    and never places an order. Returns (ok, detail). ``use_common_folder`` documents the
    EA toggle; the launcher always resolves the terminal's own Files folder path."""
    from ..bridge.paths import BridgePaths
    try:
        paths = BridgePaths(bridge_root).ensure()
        probe = Path(paths.health) / "startup_probe.json"
        atomic_write_text(probe, serialize.canonical_json(
            {"probe": "session_edge_startup", "at": now_iso}))
        ok, _ = serialize.loads(probe.read_text(encoding="utf-8"))
        try:
            probe.unlink()
        except OSError:
            pass
        if not ok:
            return False, f"probe read-back failed at {bridge_root}"
        return True, f"read/write OK at {bridge_root}"
    except Exception as exc:                             # noqa: BLE001 - report, never raise
        return False, f"cannot write/read the bridge at {bridge_root}: {exc}"


def _line(label, status, extra=""):
    dots = "." * max(4, 20 - len(label))
    return f" {label} {dots} {status}" + (f" — {extra}" if extra else "")


def _did_not_start(disc, bridge_root, *, reason="", detail=""):  # pragma: no cover - console UX
    """Plain-English startup-failure screen for a double-click operator. Never prints a
    traceback for an expected operator error, and never exposes credentials."""
    demo = account_is_demo(disc.get("trade_mode"))
    print("=" * 60)
    print(" SESSION EDGE DID NOT START")
    print("=" * 60)
    print(_line("MT5", "CONNECTED"))
    print(_line("Account", "DEMO" if demo else "NOT DEMO"))
    print(_line("Account ID", capital.mask_account(disc.get("login")) + f" @ {disc.get('server')}"))
    print(_line("Capital Base", "NOT ESTABLISHED" if reason and "CAPITAL" in (reason or "")
                else "—"))
    if reason:
        print(f"\n REASON: {reason}")
    if detail:
        print(f" {detail}")
    print("\n Action required: resolve the above, then double-click run_session_edge.bat")
    print(" again. (For first-time capital setup you can also run:")
    print("  run_session_edge.bat --initial-balance <your FTMO starting capital>)")
    print("=" * 60)


# --------------------------------------------------------------------------- #
# MT5-touching layer (Windows/terminal only)
# --------------------------------------------------------------------------- #
def _import_mt5():  # pragma: no cover - requires the MetaTrader5 package
    """Import the MetaTrader5 package (no initialize). The actual terminal-pinned
    connection is done by mt5_terminal.open_terminal so every process binds identically."""
    try:
        import MetaTrader5 as _mt5  # noqa: N813
        return _mt5
    except Exception:
        return None


def _discover(mt5):  # pragma: no cover - live terminal only
    acct = mt5.account_info()
    term = mt5.terminal_info()
    def g(o, k, d=None):
        try:
            return getattr(o, k)
        except Exception:
            return d
    return {
        "trade_mode": g(acct, "trade_mode"),
        "balance": g(acct, "balance"),
        "currency": g(acct, "currency"),
        "server": g(acct, "server", "UNKNOWN"),
        "login": g(acct, "login"),
        "data_path": g(term, "data_path"),
        "mt5_version": getattr(mt5, "__version__", "UNKNOWN"),
    }


def _spawn(module, env):  # pragma: no cover - process orchestration
    return subprocess.Popen([sys.executable, "-m", module], env=env, cwd=str(REPO_ROOT))


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main(argv=None):  # pragma: no cover - Windows/terminal orchestration
    from datetime import datetime, timezone
    p = argparse.ArgumentParser(description="Automatic DEMO Session Edge launcher")
    p.add_argument("--ftmo-verified", action="store_true",
                   help="attest the FTMO 2-Step Swing profile is verified (required)")
    p.add_argument("--symbols", default="EURUSD",
                   help="comma-separated Forex majors, e.g. EURUSD,GBPUSD "
                        "(.FX suffix added automatically)")
    p.add_argument("--symbol-suffix", default="", help="broker symbol suffix, if any")
    p.add_argument("--sessions", default=None,
                   help="comma-separated sessions to trade: SYDNEY,TOKYO,LONDON,"
                        "NEW_YORK or ALL. Omit to reuse your last saved selection "
                        "(persisted per run); first run with none defaults to LONDON. "
                        "Passing this pins it as your new default.")
    p.add_argument("--risk-profile", default=None,
                   help="risk profile: CONSERVATIVE (0.25%), MODERATE (0.50%, default), "
                        "AGGRESSIVE (1.00%), or CUSTOM (with --risk-fraction). Omit to "
                        "reuse your last saved profile; first run defaults to MODERATE. "
                        "Passing this pins it as your new default. Risk only — it never "
                        "changes strategy/session/news/FTMO logic, and is always capped "
                        "by max_risk_per_trade_pct.")
    p.add_argument("--risk-fraction", type=float, default=None,
                   help="per-trade risk fraction for --risk-profile CUSTOM (e.g. 0.004 "
                        "for 0.4%). Must be in (0, max_risk_per_trade_pct]; fails closed "
                        "otherwise. Ignored for the named profiles.")
    p.add_argument("--initial-balance", type=float, default=None,
                   help="OPTIONAL: true FTMO challenge starting capital. On first run "
                        "for an account it pins this value; normally omitted (the launcher "
                        "captures + pins it automatically). Never read from the live "
                        "account after it is pinned.")
    p.add_argument("--reinitialize", type=float, default=None,
                   help="EXPLICIT reset: overwrite the pinned capital base for the "
                        "connected account with this value (use only to correct a "
                        "wrong starting capital).")
    p.add_argument("--currency", default=None,
                   help="override account currency (default: read from account)")
    p.add_argument("--mt5-terminal-path", default=None,
                   help="Path to the MT5 terminal executable (terminal64.exe) to PIN "
                        "Python to the SAME terminal that runs the Session Edge EA. "
                        "Normally omitted (discovered + persisted on first run). Set it "
                        "if you have more than one MT5 installation.")
    p.add_argument("--runtime-dir", default=None,
                   help="override runtime dir (default: under the terminal Files folder)")
    p.add_argument("--wait-for-terminal", type=int, default=0,
                   help="seconds to keep retrying the MT5 connection before giving up "
                        "(use for auto-start at logon, e.g. 900)")
    args = p.parse_args(argv)

    # ONE terminal authority: pin every Python process to the same MT5 terminal
    # (SESSION_EDGE_MT5_TERMINAL_PATH), so Python and the EA share the same
    # MQL5\Files\session_edge_bridge. Bare initialize() could otherwise attach to a
    # different installation than the one running the EA.
    now_iso = datetime.now(timezone.utc).isoformat()
    plan = term.requested_plan(args.mt5_terminal_path, os.environ)
    mt5 = _import_mt5()
    if mt5 is None:
        print("Session Edge launcher: MetaTrader5 package unavailable — `pip install "
              "MetaTrader5` and run on the Windows/MT5 machine.", file=sys.stderr)
        return 3
    deadline = time.time() + max(0, args.wait_for_terminal)
    sel, last_err = None, None
    while True:
        try:
            sel = term.open_terminal(mt5, plan)
            break
        except term.TerminalSelectionError as exc:
            last_err = exc
            if time.time() >= deadline:
                break
            print(f"Session Edge launcher: waiting for the MT5 terminal... ({exc})",
                  file=sys.stderr)
            time.sleep(5)
    if sel is None:
        print(f"Session Edge launcher: {last_err}  (no silent fallback to another "
              f"MT5 installation).", file=sys.stderr)
        return 3
    try:
        disc = _discover(mt5)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    # The one executable every child + preflight must pin to; persist it for next run.
    terminal_exe = term.effective_terminal_exe(sel)
    disc["data_path"] = sel.get("data_path")           # bridge derives from THIS terminal
    disc["terminal_path"] = sel.get("terminal_path")
    disc["terminal_exe"] = terminal_exe
    disc["terminal_source"] = sel.get("source")
    if terminal_exe:
        try:
            term.persist(term.selection_store_path(), terminal_exe, sel.get("data_path"), now_iso)
        except Exception:                              # persistence is a convenience only
            pass

    if not account_is_demo(disc.get("trade_mode")):
        print(f"Session Edge launcher: REFUSED — account is not DEMO "
              f"(trade_mode={disc.get('trade_mode')!r}). DEMO only.", file=sys.stderr)
        return 4

    # FTMO attestation — explicit, never auto-forced
    confirm = None
    if not args.ftmo_verified and sys.stdin is not None and sys.stdin.isatty():
        print("FTMO 2-Step Swing profile attestation required.")
        print("Confirm you have verified the FTMO 2-Step Swing profile for this run.")
        confirm = input("Type VERIFIED to attest (anything else aborts): ")
    if not attestation_ok(flag=args.ftmo_verified, tty_confirm=confirm):
        print("Session Edge launcher: FTMO profile not attested — re-run with "
              "--ftmo-verified (or type VERIFIED when prompted). Nothing started.",
              file=sys.stderr)
        return 5

    if not disc.get("data_path"):
        print("Session Edge launcher: could not read terminal data_path.", file=sys.stderr)
        return 6

    bridge_root = bridge_root_from_data_path(disc["data_path"])
    runtime_dir = Path(args.runtime_dir) if args.runtime_dir else \
        Path(disc["data_path"]) / "MQL5" / "Files" / "session_edge_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    news_file = runtime_dir / "news_bundle.json"

    symbols = canonical_symbols(args.symbols.split(","))
    # Zero-friction session selection (single authority preserved): explicit --sessions
    # wins and is persisted as the new default; otherwise reuse the persisted selection;
    # otherwise default LONDON. Invalid/corrupt selection fails closed (no silent
    # fallback to a different session). runtime.config re-validates independently.
    from . import session_selection
    try:
        sessions, sessions_source = session_selection.resolve(
            args.sessions, session_selection.selection_store_path(), now_iso=now_iso)
    except session_selection.SessionSelectionError as exc:
        print(f"Session Edge launcher: invalid session selection ({exc}). Nothing "
              f"started. Re-run with --sessions SYDNEY,TOKYO,LONDON,NEW_YORK or ALL.",
              file=sys.stderr)
        return 7
    # Risk profile / sizing mode (zero-friction, persisted; ONE risk front-end). Like
    # sessions: explicit CLI wins and is persisted; else the saved profile; else
    # MODERATE. Resolves to an explicit risk_fraction bounded by max_risk_per_trade_pct
    # (fails closed above the ceiling). This is the SOLE risk-config surface; PR-3J
    # stays the sole sizer and compliance re-proves the ceiling.
    from . import risk_profile as _rp
    try:
        risk_prof, risk_frac, sizing_mode, risk_source = _rp.resolve(
            args.risk_profile, args.risk_fraction, _rp.store_path(), now_iso=now_iso)
    except _rp.RiskProfileError as exc:
        print(f"Session Edge launcher: invalid risk profile ({exc}). Nothing started. "
              f"Re-run with --risk-profile CONSERVATIVE|MODERATE|AGGRESSIVE|CUSTOM "
              f"(CUSTOM needs --risk-fraction <= {_rp.CEILING_RISK_FRACTION}).",
              file=sys.stderr)
        return 7

    currency = args.currency or disc.get("currency")
    if not currency:
        _did_not_start(disc, bridge_root, reason="ACCOUNT CURRENCY UNAVAILABLE",
                       detail="Could not read the account currency; pass --currency.")
        return 7

    # Capital base: resolve the PINNED FTMO starting capital for THIS account via the
    # single canonical owner (runtime.capital). First run captures + pins it; every
    # restart reuses the pinned value (never re-derived from live balance — H3). A
    # command-line value never silently overwrites an established base.
    store = capital.CapitalBaseStore(Path(runtime_dir) / "capital_base.json")
    try:
        res = capital.resolve_capital_base(
            store, login=disc.get("login"), server=disc.get("server"), currency=currency,
            current_balance=disc.get("balance"), cli_initial=args.initial_balance,
            reinitialize=args.reinitialize, now_iso=now_iso)
    except capital.CapitalBaseError as exc:
        res = capital.Resolution(False, reason="CAPITAL RECORD CORRUPT", message=str(exc))
    if not res.ok:
        _did_not_start(disc, bridge_root, reason=res.reason, detail=res.message)
        return 7
    balance = res.initial_balance

    # Bridge self-check (no trade): prove Python can write/read the exact bridge folder
    # the EA reads. Fail closed if it cannot.
    bh_ok, bh_detail = bridge_handshake(bridge_root, now_iso)
    if not bh_ok:
        _did_not_start(disc, bridge_root, reason="BRIDGE NOT WRITABLE", detail=bh_detail)
        return 8

    # Timezone data (reuse the preflight check; missing tzdata on Windows fails closed).
    from . import preflight as _pf
    _, tz_status, tz_detail = _pf._check_timezones()
    if tz_status == _pf.FAIL:
        _did_not_start(disc, bridge_root, reason="TIMEZONE DATA MISSING", detail=tz_detail)
        return 9

    env = build_env(
        os.environ, bridge_root=bridge_root, runtime_dir=str(runtime_dir),
        news_file=str(news_file), symbols=symbols, symbol_suffix=args.symbol_suffix,
        initial_balance=balance, account_currency=currency,
        enabled_sessions=sessions, terminal_path=disc.get("terminal_exe"),
        risk_profile=risk_prof, risk_fraction=risk_frac, sizing_mode=sizing_mode,
        ftmo_source="FTMO 2-Step Swing (operator-attested via launcher)",
        ftmo_verified_at=datetime.now(timezone.utc).date().isoformat())

    acct_id = f"{capital.mask_account(disc.get('login'))} @ {disc.get('server')}"
    term_exe = disc.get("terminal_exe") or disc.get("terminal_path") or "?"
    print("=" * 60)
    print(" SESSION EDGE STARTUP")
    print("=" * 60)
    print(_line("MT5 Terminal", "PASS", f"{disc.get('terminal_source')}: {term_exe}"))
    print(_line("DEMO Account", "PASS"))
    print(_line("Account Identity", "PASS", acct_id))
    print(_line("Capital Base", "PASS", f"{currency} {balance:,.2f}"))
    print(f"     {res.message}")
    # Trading sessions — the EFFECTIVE selection this run (single Python authority;
    # the EA never chooses sessions). ALL renders the four canonical profiles.
    _src = {"cli": "from --sessions (saved)", "persisted": "saved selection",
            "default": "default"}.get(sessions_source, sessions_source)
    if tuple(sessions) == tuple(session_selection.SUPPORTED_SESSION_IDS):
        print(_line("Trading Sessions", "PASS", f"ALL (4) — {_src}"))
        for s in sessions:
            print(f"{' ' * 26}{s}")
    else:
        print(_line("Trading Sessions", "PASS", f"{', '.join(sessions)} — {_src}"))
    # Lot sizing is fully autonomous (PR-3J is the sole live authority); the operator
    # has no manual lot control anywhere (the EA's DefaultVolume input was removed).
    print(_line("Lot Sizing", "PASS", "AUTONOMOUS — PR-3J (compliance/sizing)"))
    print(_line("Manual Lot Override", "DISABLED"))
    # Risk & Sizing configuration (front-end only; PR-3J stays the sole sizer). The
    # "Safe Risk Capacity" is the per-trade money budget = risk_fraction × pinned
    # funded capital; the actual volume is derived per-trade by PR-3J from this budget,
    # the stop distance, and broker lot metadata, and re-proven by compliance/H-1.
    _rsrc = {"cli": "from --risk-profile (saved)", "persisted": "saved profile",
             "default": "default"}.get(risk_source, risk_source)
    print(_line("Risk Profile", "PASS", f"{risk_prof} — {_rsrc}"))
    print(_line("Sizing Mode", "PASS", f"{sizing_mode} (risk-based; PR-3J)"))
    print(_line("Configured Risk", "PASS", f"{risk_frac * 100:.2f}% per trade "
                f"(cap {_rp.CEILING_RISK_FRACTION * 100:.2f}%)"))
    print(_line("Safe Risk Capacity", "PASS",
                f"{currency} {balance * risk_frac:,.2f} per trade (max loss-at-stop)"))
    print(_line("Timezone Data", tz_status, tz_detail if tz_status != _pf.PASS else ""))

    # Bridge readiness — split the old ambiguous single "Bridge PASS" (which only ever
    # proved Python could R/W a folder) into the four TRUTHFUL lines. Filesystem is the
    # Python probe above; EA Bridge Liveness is proven ONLY by a fresh, same-bridge
    # EA-written heartbeat; Instruction Health is H5; End-to-End requires BOTH filesystem
    # AND a live EA. A missing/stale EA heartbeat now reads as NOT READY, never PASS.
    from . import ea_liveness as _el
    from . import operator_status as _os
    live = _el.read_ea_status(bridge_root, datetime.now(timezone.utc),
                              expected_bridge_root_name="session_edge_bridge",
                              expected_use_common=False, expected_bridge_abspath=bridge_root)
    e2e = _os.bridge_end_to_end(bh_ok, live.state)
    print(_line("Bridge Filesystem", "PASS" if bh_ok else "FAIL", bridge_root))
    print(f"     {bh_detail}")
    print(_line("EA Bridge Liveness", live.state, live.detail))
    if not live.ok:
        print("     The EA must be attached in the SAME terminal (File > Open Data Folder), "
              "BridgeRoot=session_edge_bridge, UseCommonFolder=false, and writing "
              "health\\ea_status.json on its timer. Start/attach it, then re-check with "
              "python -m forex_swing_orb.runtime.preflight")
    print(_line("Bridge End-to-End",
                "READY" if e2e["ready"] else "NOT READY",
                "" if e2e["ready"] else "; ".join(e2e["blockers"])))
    if not disc.get("terminal_exe"):
        print("     WARNING: could not resolve the terminal executable to pin child "
              "processes; if you run more than one MT5 install, pass --mt5-terminal-path "
              "to the EA's terminal64.exe for a deterministic bind.")
    print(_line("Symbol Metadata", _pf.ENV, "verify on-machine: python -m "
                "forex_swing_orb.runtime.preflight"))
    # Canonical paths (from the existing config owners) so a diagnosis never needs a
    # screenshot to find where state lives. No secrets. The acquisition lock is the
    # exact file whose open failure yields News Acquisition Owner: UNKNOWN.
    _news_lock = str(Path(runtime_dir) / "calendar_acq.lock")
    _startup_diag = str(Path(runtime_dir) / "startup_diagnostic.json")
    print("-" * 60)
    print(" Canonical paths (for diagnostics):")
    print(f"   MT5 data path      : {disc.get('data_path')}")
    print(f"   Runtime directory  : {runtime_dir}")
    print(f"   Bridge directory   : {bridge_root}")
    print(f"   News bundle        : {news_file}")
    print(f"   News acq. lock     : {_news_lock}")
    print(f"   Startup diagnostic : {_startup_diag} (written only on a startup refusal)")
    print("-" * 60)
    print(_line("News Service", "STARTING"))
    print(_line("Producer", "STARTING"))
    print(_line("Manager", "STARTING"))
    print("=" * 60)

    # Bind children to the launcher's lifetime so an abnormal launcher exit (console
    # [X], force-kill, or a fatal error that skips `finally`) can never leave an
    # orphaned newsfeed child holding the news-acquisition OS lock. On Windows this is
    # a Job Object with kill-on-close; on POSIX it is a no-op and the terminate()+wait()
    # below remains the reaper. It only ever kills processes WE assign — never an
    # unrelated python.exe.
    from . import proc_group as _pg
    group = _pg.create_kill_on_close_group()
    procs = []
    try:
        for module in CHILDREN:
            proc = _spawn(module, env)
            group.assign(proc)
            procs.append((module, proc))
        if group.supported:
            print(_line("Child Cleanup", "PASS", "kill-on-exit bound (no orphans)"))
        print(" SESSION EDGE PROCESSES STARTED")
        print(" STARTED is not READY: the child processes are up, but end-to-end")
        print(" readiness (a LIVE EA heartbeat on this bridge, producer not blocked,")
        print(" a valid daily anchor, and fresh market data) is proven separately.")
        if not e2e["ready"]:
            print(f" Bridge is NOT end-to-end ready yet: {'; '.join(e2e['blockers'])}")
        print(" For the authoritative SYSTEM STATUS (READY / NOT READY + blockers), run:")
        print("   python -m forex_swing_orb.runtime.preflight")
        print(" (Ctrl+C to stop all)")
        print("=" * 60)
        # wait until interrupted or a child exits
        _gate = {"forex_swing_orb.newsfeed": "NEWS_ACQUISITION_OWNERSHIP / NEWS_ACQUISITION",
                 "forex_swing_orb.producer": "PRODUCER_STARTUP",
                 "forex_swing_orb.manage": "MANAGER_STARTUP"}
        while True:
            for module, proc in procs:
                rc = proc.poll()
                if rc is not None:
                    comp = module.rsplit(".", 1)[-1].upper()
                    print("=" * 60, file=sys.stderr)
                    print(f" {comp} FAILED", file=sys.stderr)
                    print(f"   Component   : {module}", file=sys.stderr)
                    print(f"   Exit code   : {rc}", file=sys.stderr)
                    print(f"   Gate        : {_gate.get(module, 'STARTUP')}", file=sys.stderr)
                    if module == "forex_swing_orb.newsfeed":
                        print(f"   Diagnostic  : {_startup_diag} (if written)", file=sys.stderr)
                        print(f"   Lock path   : {_news_lock}", file=sys.stderr)
                    print("   Disposition : SESSION EDGE NOT READY — pipeline shut down "
                          "FAIL-CLOSED", file=sys.stderr)
                    print("   (The child made the safety decision; the launcher does not "
                          "override it.)", file=sys.stderr)
                    print("=" * 60, file=sys.stderr)
                    raise KeyboardInterrupt
            try:
                procs[0][1].wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print("\nSession Edge launcher: shutting down...", file=sys.stderr)
    finally:
        for module, proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        for module, proc in procs:
            try:
                proc.wait(timeout=10)
            except Exception:
                # A child that ignored terminate() within the grace window would
                # otherwise orphan and keep the lock; the job's kill-on-close (below)
                # is the deterministic backstop that still reaps it.
                pass
        try:
            group.close()               # Windows: kill-on-close reaps any survivor
        except Exception:
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
