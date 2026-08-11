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


def build_env(base_env, *, bridge_root, runtime_dir, news_file, symbols,
              symbol_suffix, initial_balance, account_currency, ftmo_source,
              ftmo_verified_at, enabled_sessions=DEFAULT_SESSIONS,
              overlap_mode=DEFAULT_OVERLAP_MODE, calendar_provider=DEFAULT_PROVIDER):
    """Build the child environment. FTMO_PROFILE_VERIFIED is set true here because
    the caller only reaches this step AFTER the operator has attested (see main)."""
    env = dict(base_env)
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


# --------------------------------------------------------------------------- #
# MT5-touching layer (Windows/terminal only)
# --------------------------------------------------------------------------- #
def _connect():  # pragma: no cover - requires a live Windows terminal
    try:
        import MetaTrader5 as _mt5  # noqa: N813
    except Exception:
        return None
    try:
        if not _mt5.initialize():
            return None
    except Exception:
        return None
    return _mt5


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
    p.add_argument("--initial-balance", type=float, default=None,
                   help="REQUIRED: true FTMO challenge starting capital (pinned; "
                        "never read from the live account)")
    p.add_argument("--currency", default=None,
                   help="override account currency (default: read from account)")
    p.add_argument("--runtime-dir", default=None,
                   help="override runtime dir (default: under the terminal Files folder)")
    p.add_argument("--wait-for-terminal", type=int, default=0,
                   help="seconds to keep retrying the MT5 connection before giving up "
                        "(use for auto-start at logon, e.g. 900)")
    args = p.parse_args(argv)

    deadline = time.time() + max(0, args.wait_for_terminal)
    mt5 = _connect()
    while mt5 is None and time.time() < deadline:
        print("Session Edge launcher: waiting for the MT5 terminal...", file=sys.stderr)
        time.sleep(5)
        mt5 = _connect()
    if mt5 is None:
        print("Session Edge launcher: MetaTrader5 unavailable — open the terminal, "
              "log into your DEMO account, and `pip install MetaTrader5`.", file=sys.stderr)
        return 3
    try:
        disc = _discover(mt5)
    finally:
        try:
            mt5.shutdown()
        except Exception:
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
    # H3: the FTMO initial balance (challenge starting capital) MUST be explicitly
    # attested and pinned. It is NEVER re-anchored from the current live balance —
    # doing so would drift the static max-loss floor downward after any drawdown on
    # every restart. Fail closed if not provided; do not guess.
    balance = resolve_initial_balance(args.initial_balance, disc.get("balance"))
    if balance is None:
        print("Session Edge launcher: --initial-balance is REQUIRED (the true FTMO "
              "challenge starting capital, e.g. --initial-balance 50000). It is "
              "never read from the live account. Nothing started.", file=sys.stderr)
        return 7
    currency = args.currency or disc.get("currency")
    if not currency:
        print("Session Edge launcher: could not determine account currency; pass "
              "--currency. Nothing started.", file=sys.stderr)
        return 7
    live_bal = disc.get("balance")
    if isinstance(live_bal, (int, float)) and live_bal and float(live_bal) != float(balance):
        where = "below" if float(live_bal) < float(balance) else "above"
        print(f"Session Edge launcher: live balance ({live_bal}) is {where} the "
              f"attested initial ({balance}); keeping initial PINNED — the max-loss "
              f"floor is unchanged.", file=sys.stderr)

    env = build_env(
        os.environ, bridge_root=bridge_root, runtime_dir=str(runtime_dir),
        news_file=str(news_file), symbols=symbols, symbol_suffix=args.symbol_suffix,
        initial_balance=balance, account_currency=currency,
        ftmo_source="FTMO 2-Step Swing (operator-attested via launcher)",
        ftmo_verified_at=datetime.now(timezone.utc).date().isoformat())

    print("=" * 66)
    print(" Session Edge — automatic DEMO launcher")
    print(f"  account   : DEMO ({disc.get('server')})   {currency}")
    print(f"  ftmo init : {balance} (pinned, attested)")
    print(f"  symbols   : {', '.join(symbols)}")
    print(f"  bridge    : {bridge_root}")
    print(f"  runtime   : {runtime_dir}")
    print(f"  news      : real calendar ({DEFAULT_PROVIDER}) -> {news_file}")
    print("  starting  : newsfeed + producer + manager   (Ctrl+C to stop all)")
    print("=" * 66)

    procs = []
    try:
        for module in CHILDREN:
            procs.append((module, _spawn(module, env)))
        # wait until interrupted or a child exits
        while True:
            for module, proc in procs:
                rc = proc.poll()
                if rc is not None:
                    print(f"Session Edge launcher: '{module}' exited (code {rc}); "
                          f"stopping the pipeline.", file=sys.stderr)
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
                pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
