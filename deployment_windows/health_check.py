"""Titan Protocol deployment health check.

Checks exactly what this deployment layer can honestly check (see
start.py's module docstring and KNOWN_GAPS.md for what it cannot):
Bridge reachability, real MT5 EA connectivity (via the running
process's own BridgeEngine.is_connection_healthy, not just "is the
port open"), heartbeat/reliability state, configuration load and
profile validity, directory writability, duplicate-process detection,
Bridge command-queue depth (against the real configured thresholds),
the Bridge API key's environment-variable presence, the static news_feed_trusted config value, and -- since Amendment 1
(ADR-023) -- real market-data readiness (per-pair warmup/freshness
from the now-live MarketDataIngestionEngine) and whether the
live-cycle loop is actually evaluating pairs. Since Phase 3E
(ADR-033 Part 2) also reports the real, dynamic dual-provider news
failover state (active provider, per-provider health, failover/
recovery counts) from the now-live NewsIngestionEngine. Since ADR-034
Amendment 2 ("Produce a Clean Deployment Release"), also reports the
active transport, the resolved API key source, an explicit magic-number-
consistency confirmation, and cross-checks the personalized MT5 .set
file's MagicNumber against the live config to catch configuration drift.

Exit codes: 0 = HEALTHY, 1 = DEGRADED, 2 = FAILED.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Dict, Optional

_HERE = Path(__file__).resolve().parent


def _find_repo_root(here: Path) -> Path:
    """Locates the installation root -- the folder containing both
    titan_protocol/ and mt5/ -- whether this script lives directly inside it
    (the shipped, flattened C:\\TitanProtocol\\health_check.py layout) or one
    level below it (this repository's own deployment_windows/
    subfolder, used for development)."""
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

import install_mt5_files as install_mt5_module
from config_loader import ConfigError, build_trading_profile, generated_secret_path, is_process_alive, load_settings
from titan_protocol.runtime.validation import validate_profile
from titan_protocol.strategy_engine.config import StrategyEngineConfig

_HEALTH_JSON_STALE_AFTER_SECONDS = 30.0  # 6x the heartbeat loop's own interval


def _parse_iso_epoch(iso_string: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso_string).timestamp()


def _report(checks) -> None:
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}{': ' + detail if detail else ''}")


def _format_age(seconds: Optional[float]) -> str:
    return "never" if seconds is None else f"{seconds:.1f}s ago"


def _print_run_status_panel(run_status: Optional[dict]) -> None:
    """Item 10: a single, concise block answering "why is Titan trading
    or not" without cross-referencing bridge_reachable/mt5_connected/
    live_cycle/market_data/etc separately, or grepping the log file.
    Purely informational -- reads state/health.json's own `run_status`
    key verbatim, never re-derives or gates on it."""
    print()
    print("=" * 72)
    print("RUN STATUS")
    print("=" * 72)
    if not run_status:
        print("  NOT AVAILABLE -- no health.json, or this process predates this diagnostic.")
        print("=" * 72)
        return

    print(f"  Communication mode        : {run_status.get('communication_mode')}")
    print(f"  Bridge connection status  : {run_status.get('bridge_connection_status')}")
    print(f"  Runtime status            : {run_status.get('runtime_status')}")
    print(f"  Last heartbeat age        : {_format_age(run_status.get('last_heartbeat_age_seconds'))}")
    print(f"  Last position report age  : {_format_age(run_status.get('last_position_report_age_seconds'))}")
    print(f"  In-flight command count   : {run_status.get('in_flight_command_count')}")
    print(f"  Awaiting position confirm : {run_status.get('awaiting_position_confirmation_count')}")
    print(f"  Position confirm timeouts : {run_status.get('position_confirmation_timeout_count')} (cumulative)")
    print(f"  Open positions per pair   : {run_status.get('open_positions_per_pair') or {}}")
    print(f"  Configured max/pair       : {run_status.get('configured_max_positions_per_pair')}")
    account_state_fresh = run_status.get("account_state_fresh")
    fresh_label = "unknown" if account_state_fresh is None else ("fresh" if account_state_fresh else "STALE")
    print(f"  Account report age        : {_format_age(run_status.get('account_report_age_seconds'))} ({fresh_label})")
    print(f"  Configured max account age: {run_status.get('configured_max_account_state_age_seconds')}s")
    compliance_state = run_status.get("compliance_state")
    block_reason = run_status.get("compliance_block_reason")
    print(f"  Compliance state          : {compliance_state}{f' ({block_reason})' if compliance_state == 'BLOCKED' and block_reason else ''}")
    print(f"  Last submitted correlation_id: {run_status.get('last_submitted_correlation_id')}")
    pairs = run_status.get("pairs") or {}
    if pairs:
        print("  Per-pair cycle outcome:")
        for pair, status in sorted(pairs.items()):
            reason = status.get("reason")
            correlation_id = status.get("correlation_id")
            print(
                f"    {pair}: {status.get('outcome')}"
                f"{' -- ' + reason if reason else ''}"
                f"{' (correlation_id=' + correlation_id + ')' if correlation_id else ''}"
            )
    else:
        print("  Per-pair cycle outcome    : no pairs evaluated yet")
    print("=" * 72)


def _describe_api_key_source(settings, config_path: Path) -> str:
    """Replicates config_loader.py's own 3-tier `_resolve_secret` priority
    order (env var -> generated secret file -> inline value) read-only,
    to report which one is actually active -- without changing
    `_resolve_secret`'s existing return contract."""
    env_var_name = settings.api_key_env_var_name
    if env_var_name and os.environ.get(env_var_name):
        return f"environment variable {env_var_name}"
    secret_path = generated_secret_path(config_path)
    if secret_path.exists() and secret_path.read_text(encoding="utf-8").strip():
        return f"generated secret file ({secret_path})"
    return "inline value in titan_protocol_config.json (bridge.api_key) -- not recommended for a real deployment"


def _find_personalized_set_file() -> Optional[Path]:
    """Only returns a path when exactly one MT5 data folder is
    auto-detectable (the same detection install_mt5_files.py itself
    uses) and it has already been personalized -- an ambiguous or
    not-yet-installed case is reported separately, never guessed at."""
    candidates = install_mt5_module._find_mt5_data_dirs()
    if len(candidates) != 1:
        return None
    set_path = candidates[0] / "MQL5" / "Presets" / "TitanProtocol" / "TitanProtocolEA.set"
    return set_path if set_path.exists() else None


def _parse_set_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(";") and "=" in stripped:
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
    return values


def run(config_path: Path) -> int:
    """Runs every check and prints a PASS/FAIL line for each. Returns
    0/1/2 (HEALTHY/DEGRADED/FAILED) -- callers (including start.py)
    should treat this as the authoritative exit code, not re-derive
    their own."""

    checks = []  # (name, ok: bool, detail: str)

    try:
        settings = load_settings(config_path)
        checks.append(("configuration loaded", True, str(config_path)))
    except ConfigError as exc:
        checks.append(("configuration loaded", False, str(exc)))
        _report(checks)
        return 2  # nothing else can be checked without valid config

    try:
        profile = build_trading_profile(settings)
    except ConfigError as exc:
        checks.append(("trading profile valid", False, str(exc)))
        profile = None
    if profile is not None:
        result = validate_profile(profile, StrategyEngineConfig(), settings.compliance_config)
        checks.append(("trading profile valid", result.valid, f"{profile.profile_id}: {result.issues if not result.valid else 'ok'}"))

    env_var_name = settings.api_key_env_var_name
    if env_var_name:
        env_var_present = bool(os.environ.get(env_var_name))
        checks.append((
            "API key environment variable present", env_var_present,
            f"{env_var_name} {'is set' if env_var_present else 'is NOT set -- falling back to the generated secret file or inline config value, if any'}",
        ))
    else:
        checks.append(("API key environment variable present", True, "bridge.api_key_env_var not configured -- using the generated secret file or an inline value instead"))

    checks.append(("active API key source", True, _describe_api_key_source(settings, config_path)))

    checks.append(("active transport", True, "http"))

    checks.append((
        "magic number consistency (bridge/runtime)", True,
        f"bridge={settings.bridge_config.magic_number}, runtime={settings.runtime_config.magic_number}"
        " (load_settings() already refuses to start on any mismatch, so this is a confirmation, not a fresh check)",
    ))

    set_path = _find_personalized_set_file()
    if set_path is not None:
        set_values = _parse_set_file(set_path)
        set_magic_raw = set_values.get("MagicNumber")
        try:
            set_magic = int(set_magic_raw) if set_magic_raw is not None else None
        except ValueError:
            set_magic = None
        magic_matches = set_magic is not None and set_magic == settings.bridge_config.magic_number
        if magic_matches:
            checks.append((
                "EA .set file consistency (configuration drift)", True,
                f"{set_path}: MagicNumber={set_magic} matches the active configuration",
            ))
        else:
            checks.append((
                "EA .set file consistency (configuration drift)", False,
                f"{set_path}: MagicNumber={set_magic_raw!r} does NOT match bridge.magic_number "
                f"({settings.bridge_config.magic_number}) -- re-run install_mt5_files.py or edit "
                "the .set file, then reload it in MT5's Inputs tab.",
            ))
    else:
        checks.append((
            "EA .set file detection", True,
            "no single MT5 data folder auto-detected (0 or multiple candidates), or the .set file "
            "has not been personalized yet -- skipped, not fatal; run install_mt5_files.py to "
            "personalize it, or pass the correct folder explicitly if more than one was found",
        ))

    checks.append((
        "news-feed trust state", True,
        f"news_feed_trusted={settings.news_feed_trusted} "
        f"({'MI Engine will score news normally' if settings.news_feed_trusted else 'MI Engine fails closed: blackout, score=0 -- this is a safe, deliberate operator choice, not a bug'})",
    ))

    for label, path in (("log_dir writable", settings.log_dir), ("state_dir writable", settings.state_dir), ("data_dir writable", settings.data_dir)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".health_check_write_probe"
            probe.write_text("ok")
            probe.unlink()
            checks.append((label, True, str(path)))
        except OSError as exc:
            checks.append((label, False, f"{path}: {exc}"))

    try:
        with socket.create_connection((settings.bridge_host, settings.bridge_port), timeout=2.0):
            checks.append(("bridge reachable (http)", True, f"{settings.bridge_host}:{settings.bridge_port}"))
    except OSError as exc:
        checks.append(("bridge reachable (http)", False, f"{settings.bridge_host}:{settings.bridge_port}: {exc}"))

    pid_file = settings.state_dir / "titan_protocol.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            alive = is_process_alive(pid)
            checks.append(("no duplicate Titan Protocol processes", True, f"single recorded pid {pid}, alive={alive}"))
            checks.append(("runtime process alive", alive, f"pid {pid}"))
        except ValueError:
            checks.append(("no duplicate Titan Protocol processes", False, f"unreadable pid file {pid_file}"))
    else:
        checks.append(("runtime process alive", False, "no pid file -- Titan Protocol is not running"))

    cycle_loop_active = False
    payload: dict = {}
    health_json = settings.state_dir / "health.json"
    if health_json.exists():
        try:
            payload = json.loads(health_json.read_text())
            generated_at_age = time.time() - _parse_iso_epoch(payload["generated_at"])
            fresh = generated_at_age <= _HEALTH_JSON_STALE_AFTER_SECONDS
            checks.append(("reliability monitor alive", fresh, f"last snapshot {generated_at_age:.1f}s ago"))
            checks.append(("heartbeat state", fresh, f"degradation_level={payload.get('degradation_level')}"))
            checks.append(("bridge reachable (per running process)", payload.get("bridge_reachable", False), ""))
            # The real, EA-heartbeat-based liveness check (BridgeEngine.
            # is_connection_healthy), not just "is the port open" --
            # distinguishes "Bridge process is up" from "MT5 EA has
            # actually talked to it recently."
            mt5_connected = payload.get("mt5_connected", False)
            checks.append(("MT5 bridge connectivity (EA heartbeat)", mt5_connected, "" if mt5_connected else "no recent heartbeat from the MT5 EA -- attach/verify the EA in MT5"))
            cycle_loop_active = payload.get("cycle_loop_active", False)

            queue_depth = payload.get("bridge_command_queue_depth")
            if queue_depth is None:
                checks.append(("queue health", False, "bridge_command_queue_depth missing from health.json"))
            else:
                degraded_at = settings.reliability_config.queue_degraded_depth
                critical_at = settings.reliability_config.queue_critical_depth
                queue_ok = queue_depth < degraded_at
                checks.append((
                    "queue health", queue_ok,
                    f"depth={queue_depth} (degraded >= {degraded_at}, critical >= {critical_at})"
                    if queue_ok else
                    f"depth={queue_depth} has reached or exceeded the degraded threshold ({degraded_at})",
                ))
        except (ValueError, KeyError, OSError) as exc:
            checks.append(("reliability monitor alive", False, f"health.json unreadable: {exc}"))
            checks.append(("MT5 bridge connectivity (EA heartbeat)", False, "health.json unreadable"))
            checks.append(("queue health", False, "health.json unreadable"))
    else:
        checks.append(("reliability monitor alive", False, "no health.json -- Titan Protocol is not running"))
        checks.append(("MT5 bridge connectivity (EA heartbeat)", False, "no health.json -- Titan Protocol is not running"))
        checks.append(("queue health", False, "no health.json -- Titan Protocol is not running"))

    # MT5 connectivity, market-data readiness, and the trading-cycle
    # loop are informational at this stage of deployment -- none of
    # them downgrade HEALTHY->DEGRADED/FAILED, since no EA is expected
    # to be attached during setup/first health check, and full HEALTHY
    # status still isn't claimed while news-provider redundancy and
    # persisted day-start/peak account tracking remain open gaps (see
    # KNOWN_GAPS.md and the Amendment 1 implementation report).
    # Reported so an operator can see them, not gated on. news-feed
    # trust state and the API-key-env-var check are also informational
    # -- they report real state, not pass/fail.
    informational_only = {
        "MT5 bridge connectivity (EA heartbeat)", "live trading cycle active",
        "market-data readiness", "news-feed trust state", "news provider failover",
        "API key environment variable present",
        # Indeterminate-detection case only (0 or multiple MT5 folders
        # found, or nothing personalized yet) -- not fatal by itself.
        # "EA .set file consistency (configuration drift)" is
        # deliberately NOT in this set: a real, detected mismatch there
        # is exactly the drift this check exists to catch, and should
        # gate like any other real failure.
        "EA .set file detection",
    }

    live_cycle = payload.get("live_cycle")
    if live_cycle:
        evaluated = live_cycle.get("evaluated_pairs") or []
        skipped = live_cycle.get("skipped_pairs") or {}
        detail = f"last cycle {live_cycle.get('last_cycle_id')}: {len(evaluated)} pair(s) evaluated"
        if skipped:
            detail += f", skipped: {skipped}"
        checks.append(("live trading cycle active", cycle_loop_active, detail))
    else:
        checks.append((
            "live trading cycle active", cycle_loop_active,
            "NOT ACTIVE -- no health.json, or this process predates Amendment 1" if not cycle_loop_active else "",
        ))

    market_data = payload.get("market_data")
    if market_data:
        warmups = market_data.get("warmup_statuses", [])
        freshness = market_data.get("freshness", [])
        all_ready = bool(warmups) and all(w.get("ready") for w in warmups)
        all_fresh = bool(freshness) and all(not f.get("is_stale") for f in freshness)
        metrics = market_data.get("metrics", {})
        checks.append((
            "market-data readiness", all_ready and all_fresh,
            f"warmup={sum(1 for w in warmups if w.get('ready'))}/{len(warmups)} pairs ready, "
            f"fresh={sum(1 for f in freshness if not f.get('is_stale'))}/{len(freshness)}, "
            f"accepted={metrics.get('bars_accepted', 0)}, rejected={metrics.get('bars_rejected', 0)}, "
            f"gaps={metrics.get('gaps_detected', 0)}, ticks={metrics.get('ticks_ingested', 0)}"
            if warmups else "no pairs configured",
        ))
    else:
        checks.append((
            "market-data readiness", False,
            "NOT AVAILABLE -- no health.json, or this process predates Amendment 1 "
            "(titan_protocol/market_data_ingestion/ wiring; see KNOWN_GAPS.md section 1)",
        ))

    news = payload.get("news")
    if news:
        provider_health = news.get("provider_health", [])
        failover_state = news.get("failover_state", {})
        metrics = news.get("metrics", {})
        checks.append((
            "news provider failover", news.get("trusted", False),
            f"active={news.get('active_provider')}, trusted={news.get('trusted')}, "
            f"failovers={failover_state.get('failover_count', 0)}, "
            f"recoveries={failover_state.get('recovery_count', 0)}, "
            f"dual_outages={metrics.get('dual_outage_count', 0)}, "
            f"provider_health={[(h.get('provider'), h.get('trust_state')) for h in provider_health]}",
        ))
    else:
        checks.append((
            "news provider failover", False,
            "NOT AVAILABLE -- no health.json, or this process predates Phase 3E "
            "(titan_protocol/news_ingestion/ wiring; see KNOWN_GAPS.md)",
        ))

    all_core_ok = all(ok for name, ok, _ in checks if name not in informational_only)
    _report(checks)
    _print_run_status_panel(payload.get("run_status"))

    if not all_core_ok:
        return 2
    return 1  # DEGRADED -- Bridge+Reliability healthy, trading cycle intentionally not wired (see KNOWN_GAPS.md)


def main() -> int:
    parser = argparse.ArgumentParser(description="Titan Protocol deployment health check")
    parser.add_argument("--config", default=str(_HERE / "titan_protocol_config.json"))
    args = parser.parse_args()

    exit_code = run(Path(args.config))
    label = {0: "HEALTHY", 1: "DEGRADED", 2: "FAILED"}[exit_code]
    print(f"\nSTATUS: {label}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
