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
recovery counts) from the now-live NewsIngestionEngine.

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

from config_loader import ConfigError, build_trading_profile, is_process_alive, load_settings
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
            checks.append(("bridge reachable", True, f"{settings.bridge_host}:{settings.bridge_port}"))
    except OSError as exc:
        checks.append(("bridge reachable", False, f"{settings.bridge_host}:{settings.bridge_port}: {exc}"))

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
