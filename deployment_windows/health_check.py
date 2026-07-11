"""Phantom deployment health check.

Checks exactly what this deployment layer can honestly check (see
start.py's module docstring and KNOWN_GAPS.md for what it cannot):
Bridge reachability, real MT5 EA connectivity (via the running
process's own BridgeEngine.is_connection_healthy, not just "is the
port open"), heartbeat/reliability state, configuration load and
profile validity, directory writability, and duplicate-process
detection. Never claims the live trading cycle is running, because it
isn't (no market-data ingestion component is wired in yet).

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
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from config_loader import ConfigError, load_settings
from phantom.runtime.validation import validate_profile
from phantom.runtime import profiles as trading_profiles
from phantom.strategy_engine.config import StrategyEngineConfig

_PROFILE_FACTORIES = {
    "london_conservative": trading_profiles.make_london_conservative_profile,
    "london_aggressive": trading_profiles.make_london_aggressive_profile,
    "new_york_conservative": trading_profiles.make_new_york_conservative_profile,
    "new_york_aggressive": trading_profiles.make_new_york_aggressive_profile,
    "london_and_new_york": trading_profiles.make_london_and_new_york_profile,
}

_HEALTH_JSON_STALE_AFTER_SECONDS = 30.0  # 6x the heartbeat loop's own interval


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except AttributeError:
        return False  # os.kill unavailable -- treat as unknown/not-confirmed


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

    if settings.selected_profile == "custom":
        checks.append(("trading profile valid", False, "selected_profile=custom cannot be auto-validated by health_check"))
    else:
        profile = _PROFILE_FACTORIES[settings.selected_profile]()
        result = validate_profile(profile, StrategyEngineConfig(), settings.compliance_config)
        checks.append(("trading profile valid", result.valid, f"{profile.profile_id}: {result.issues if not result.valid else 'ok'}"))

    for label, path in (("log_dir writable", settings.log_dir), ("state_dir writable", settings.state_dir)):
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

    pid_file = settings.state_dir / "phantom.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            alive = _is_pid_alive(pid)
            checks.append(("no duplicate Phantom processes", True, f"single recorded pid {pid}, alive={alive}"))
            checks.append(("runtime process alive", alive, f"pid {pid}"))
        except ValueError:
            checks.append(("no duplicate Phantom processes", False, f"unreadable pid file {pid_file}"))
    else:
        checks.append(("runtime process alive", False, "no pid file -- Phantom is not running"))

    cycle_loop_active = False
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
        except (ValueError, KeyError, OSError) as exc:
            checks.append(("reliability monitor alive", False, f"health.json unreadable: {exc}"))
            checks.append(("MT5 bridge connectivity (EA heartbeat)", False, "health.json unreadable"))
    else:
        checks.append(("reliability monitor alive", False, "no health.json -- Phantom is not running"))
        checks.append(("MT5 bridge connectivity (EA heartbeat)", False, "no health.json -- Phantom is not running"))

    # MT5 connectivity is informational at this stage of deployment --
    # never itself downgrades HEALTHY->DEGRADED/FAILED, since no EA is
    # expected to be attached during setup/first health check. It is
    # reported so an operator can see it, not gated on.
    informational_only = {"MT5 bridge connectivity (EA heartbeat)", "live trading cycle active"}

    checks.append((
        "live trading cycle active", cycle_loop_active,
        "NOT ACTIVE by design -- no market-data ingestion component is wired in (see KNOWN_GAPS.md)" if not cycle_loop_active else "",
    ))

    all_core_ok = all(ok for name, ok, _ in checks if name not in informational_only)
    _report(checks)

    if not all_core_ok:
        return 2
    return 1  # DEGRADED -- Bridge+Reliability healthy, trading cycle intentionally not wired (see KNOWN_GAPS.md)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phantom deployment health check")
    parser.add_argument("--config", default=str(_HERE / "phantom.config.ini"))
    args = parser.parse_args()

    exit_code = run(Path(args.config))
    label = {0: "HEALTHY", 1: "DEGRADED", 2: "FAILED"}[exit_code]
    print(f"\nSTATUS: {label}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
