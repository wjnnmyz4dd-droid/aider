"""Real-MT5 validation evidence gatherer (Final Release Hardening,
requirement 5 -- companion script to REAL_MT5_VALIDATION_CHECKLIST.md).

This script does NOT verify anything on that checklist -- nothing here
can substitute for a real MetaEditor compile, a real demo-chart attach,
or a real broker order fill. What it does: reads this deployment's own
already-running evidence (`state/health.json`, `state/
compliance_state.json`) and prints it in the shape an operator working
through the checklist needs, so they aren't hand-parsing JSON files
mid-verification. Every line printed is an already-computed value from
a file this deployment itself wrote -- this script computes nothing
new and decides nothing.

Usage: `python verify_real_mt5_readiness.py [path/to/titan_protocol_config.json]`
Exit code is always 0 -- this is an evidence report, not a pass/fail
gate (see health_check.py for the pass/fail health check)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _find_repo_root(here: Path) -> Path:
    for candidate in (here, here.parent):
        if (candidate / "titan_protocol").is_dir() and (candidate / "mt5").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate the Titan Protocol installation root (a folder containing "
        f"both titan_protocol/ and mt5/) starting from {here} -- extract the full "
        "release package before running this script."
    )


_REPO_ROOT = _find_repo_root(_HERE)
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_HERE))

from config_loader import ConfigError, load_settings  # noqa: E402


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _print_health_json(state_dir: Path) -> None:
    _print_header("state/health.json (checklist sections 2, 3, 7)")
    health_path = state_dir / "health.json"
    if not health_path.exists():
        print("  not found -- Titan Protocol is not currently running (start.py never wrote it)")
        return
    try:
        payload = json.loads(health_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable: {exc!r}")
        return

    generated_at = payload.get("generated_at")
    print(f"  generated_at: {generated_at}")
    print(f"  degradation_level: {payload.get('degradation_level')}")
    print(f"  bridge_reachable: {payload.get('bridge_reachable')}")
    print(f"  mt5_connected (EA heartbeat seen recently): {payload.get('mt5_connected')}")
    print(f"  bridge_command_queue_depth: {payload.get('bridge_command_queue_depth')}")
    print(f"  cycle_loop_active: {payload.get('cycle_loop_active')}")

    market_data = payload.get("market_data")
    if market_data is not None:
        print("  market_data warmup (checklist 2.4):")
        for status in market_data.get("warmup_statuses", []):
            print(
                f"    {status['symbol']} [{status['timeframe']}]: "
                f"{status['bars_received']}/{status['bars_required']} bars, ready={status['ready']}"
            )
        print("  market_data freshness (checklist 2.6):")
        for freshness in market_data.get("freshness", []):
            print(f"    {freshness['symbol']} [{freshness['timeframe']}]: is_stale={freshness['is_stale']}")
    else:
        print("  market_data: not available in this health.json")

    news = payload.get("news")
    if news is not None:
        print("  news failover state (checklist 7):")
        print(f"    active_provider: {news.get('active_provider')}, trusted: {news.get('trusted')}")
        failover_state = news.get("failover_state", {})
        print(
            f"    failover_count: {failover_state.get('failover_count')}, "
            f"recovery_count: {failover_state.get('recovery_count')}"
        )
    else:
        print("  news: not available in this health.json")


def _print_compliance_state(state_dir: Path) -> None:
    _print_header("state/compliance_state.json (checklist section 6)")
    state_path = state_dir / "compliance_state.json"
    if not state_path.exists():
        print("  not found -- no persisted compliance state yet (bootstraps on first reported account balance)")
        return
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable: {exc!r} -- this itself is checklist-relevant evidence (corruption/fail-closed path)")
        return

    print(f"  schema_version: {payload.get('schema_version')}")
    print(f"  trading_day_id: {payload.get('trading_day_id')}")
    print(f"  trading_days_count: {payload.get('trading_days_count')}")
    print(f"  daily_starting_balance: {payload.get('daily_starting_balance')}")
    print(f"  peak_balance: {payload.get('peak_balance')}")
    print(f"  last_reset_at: {payload.get('last_reset_at')}")
    lock = payload.get("compliance_lock", {})
    print(f"  compliance_lock.active: {lock.get('active')}")
    if lock.get("active"):
        print(f"    reason: {lock.get('reason')}")
        print(f"    locked_at: {lock.get('locked_at')}")
        print(f"    resets_at: {lock.get('resets_at')}")


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO_ROOT / "titan_protocol_config.json"
    print(f"Titan Protocol real-MT5 readiness evidence -- {datetime.now(timezone.utc).isoformat()}")
    print(f"Config: {config_path}")

    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED to load configuration: {exc}", file=sys.stderr)
        return 1

    _print_health_json(settings.state_dir)
    _print_compliance_state(settings.state_dir)

    print(
        "\nThis report gathers already-available software-side evidence only. "
        "It does NOT verify MetaEditor compilation, demo-chart attach, real order "
        "execution, or any other item on REAL_MT5_VALIDATION_CHECKLIST.md -- work "
        "through that checklist by hand against a real MT5 terminal, using this "
        "output to speed up filling in sections 2, 3, 6, and 7."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
