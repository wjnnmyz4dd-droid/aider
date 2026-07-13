"""Titan Protocol live runtime launcher (Python Deployment Manager).

HONESTY NOTE -- read before assuming this starts live trading:

This script wires together every engine's REAL, existing, public
constructor exactly as the titan_protocol/ test suite and
PHANTOM_MT5_DEPLOYMENT_AUDIT.md's own Runtime Startup Order describe --
it introduces zero new trading logic, zero new engine behavior, and no
architectural redesign. What it starts:

  1. The Bridge HTTP service (titan_protocol.bridge.server.serve) -- the real,
     exported, public function the EA's WebRequest calls target.
  2. The five core trading engines (Evidence, Market Intelligence,
     Strategy, Risk, Compliance) and the Runtime Orchestrator wired to
     them, per titan_protocol/runtime/engine.py's real constructor signature.
  3. The Reliability Engine, self-monitoring this process's own
     liveness, the Bridge's reachability, and -- via
     BridgeEngine.is_connection_healthy -- whether the MT5 EA has
     actually heartbeated recently (not just whether the port is open).

What it deliberately does NOT do, and will not silently pretend to do:
`RuntimeOrchestrator.run_cycle()` requires live bars, news events,
spreads, portfolio state, and account state supplied by the CALLER for
every cycle. Nothing in the minimum live deployment package fetches
that from MT5 or a market-data provider -- the Bridge's own protocol
(heartbeat/account/positions/orders/trade-transaction/error/execution-
report/commands-poll) is entirely about EXECUTION, never market data.
Building a live trading cycle loop would require a Market Data
Ingestion component with its own Accepted ADR (see docs/adr/ADR-033 --
`titan_protocol/market_data_ingestion/` exists but is not yet wired into a
live entry point). This script reports its real status --
**DEGRADED, never HEALTHY** -- both on-screen and in state/health.json,
and never claims otherwise. See KNOWN_GAPS.md.

Two modes:
  `python start.py`               -- launches the runtime as a
                                      detached background process,
                                      waits briefly, runs a health
                                      check, prints HEALTHY/DEGRADED/
                                      FAILED, and returns control to
                                      the caller.
  `python start.py --foreground`  -- IS the long-running process
                                      (what the above mode launches
                                      internally); blocks until
                                      stopped.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _find_repo_root(here: Path) -> Path:
    """Locates the installation root -- the folder containing both
    titan_protocol/ and mt5/ -- whether this script lives directly inside it
    (the shipped, flattened C:\\TitanProtocol\\start.py layout) or one level
    below it (this repository's own deployment_windows/ subfolder, used
    for development)."""
    for candidate in (here, here.parent):
        if (candidate / "titan_protocol").is_dir() and (candidate / "mt5").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate the Titan Protocol installation root (a folder containing "
        f"both titan_protocol/ and mt5/) starting from {here} -- extract the full "
        "release package before running this script."
    )


_REPO_ROOT = _find_repo_root(_HERE)
sys.path.insert(0, str(_REPO_ROOT))  # so `import titan_protocol` works
sys.path.insert(0, str(_HERE))

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.server import serve as bridge_serve
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.reliability.engine import ReliabilityEngine
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.validation import validate_profile
from titan_protocol.runtime import profiles as trading_profiles
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.engine import StrategyEngine

from config_loader import ConfigError, load_settings

_PROFILE_FACTORIES = {
    "london_conservative": trading_profiles.make_london_conservative_profile,
    "london_aggressive": trading_profiles.make_london_aggressive_profile,
    "new_york_conservative": trading_profiles.make_new_york_conservative_profile,
    "new_york_aggressive": trading_profiles.make_new_york_aggressive_profile,
    "london_and_new_york": trading_profiles.make_london_and_new_york_profile,
}

_HEARTBEAT_INTERVAL_SECONDS = 5.0
_RESTARTABLE_ENGINES = ("evidence_engine", "market_intelligence", "strategy_engine", "risk_engine")

_shutdown_event = threading.Event()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _venv_python() -> Path:
    return _HERE / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def _check_running_under_venv() -> None:
    """Warn (never block) if a `.venv` exists next to this script but
    the currently running interpreter isn't it.

    This used to fail closed, but Titan Protocol's live runtime has zero
    third-party dependencies (see requirements.txt) -- the venv adds no
    actual functional isolation today, so refusing to run under a
    different interpreter that can equally well import `titan_protocol/`
    would only get in the way of the plain `python start.py` /
    `python stop.py` workflow install.py sets up. Prints a note and
    continues either way.

    Compares `sys.prefix` (where the running interpreter's environment
    root is), not `sys.executable` -- on POSIX, `venv` creates the
    interpreter as a symlink to the base install, so resolving symlinks
    on the executable path collapses both to the same target and the
    check would never fire. `sys.prefix` still correctly points at
    `.venv` for a venv-launched interpreter on both POSIX and Windows.
    """
    venv_python = _venv_python()
    if not venv_python.exists():
        return  # no venv created yet (e.g. deploy.py hasn't run) -- deploy.py's own check owns that gap
    venv_dir = _HERE / ".venv"
    try:
        running_from_venv = Path(sys.prefix).resolve() == venv_dir.resolve()
    except OSError:
        running_from_venv = False
    if not running_from_venv:
        print(
            f"NOTE: not running under the local virtual environment "
            f"(found .venv at {venv_python.parent.parent}, but the current "
            f"interpreter is {sys.executable}). Continuing anyway -- "
            "Titan Protocol's runtime has no third-party dependencies, so this makes "
            f"no functional difference. Use \"{venv_python}\" start.py instead "
            "if you ever do add a dependency that only lives in the venv.",
        )


def _setup_logging(log_dir: Path, level_name: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"titan_protocol_{timestamp}.log", maxBytes=25 * 1024 * 1024, backupCount=10, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def _write_pid_file(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_file = state_dir / "titan_protocol.pid"
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text().strip())
            os.kill(existing_pid, 0)  # raises OSError if no such process
            raise RuntimeError(
                f"Titan Protocol already appears to be running (pid {existing_pid} in {pid_file}). "
                "Refusing to start a second instance -- run stop.py first if that pid is stale."
            )
        except (ValueError, OSError):
            pass  # stale/unreadable pid file -- safe to overwrite
    pid_file.write_text(str(os.getpid()))
    return pid_file


def _bridge_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _write_health_snapshot(state_dir: Path, reliability: ReliabilityEngine, bridge_engine: BridgeEngine, bridge_host: str, bridge_port: int, queue_depth: int) -> None:
    now = _utc_now()
    snapshot = reliability.evaluate_health(now)
    payload = {
        "generated_at": now.isoformat(),
        "degradation_level": snapshot.degradation_level.value,
        "component_health": [
            {"component": c.component, "state": c.state.value, "last_heartbeat_at": c.last_heartbeat_at.isoformat() if c.last_heartbeat_at else None}
            for c in snapshot.component_health
        ],
        "bridge_reachable": _bridge_reachable(bridge_host, bridge_port),
        "mt5_connected": bridge_engine.is_connection_healthy,
        "bridge_command_queue_depth": queue_depth,
        "cycle_loop_active": False,
        "cycle_loop_inactive_reason": (
            "No market-data ingestion component is wired into this entry point -- "
            "see KNOWN_GAPS.md. Bridge (execution channel) and Reliability (this "
            "health monitor) are live; the trading decision cycle is not."
        ),
    }
    (state_dir / "health.json").write_text(json.dumps(payload, indent=2))


def _heartbeat_loop(reliability: ReliabilityEngine, bridge_engine: BridgeEngine, command_queue: CommandQueue, state_dir: Path, bridge_host: str, bridge_port: int) -> None:
    logger = logging.getLogger("titan_protocol.deploy.heartbeat")
    while not _shutdown_event.is_set():
        now = _utc_now()
        for component in _RESTARTABLE_ENGINES:
            # Process-liveness heartbeat: this process is alive and these
            # engine objects were constructed and remain importable/usable.
            # This is NOT a trade-cycle heartbeat -- no cycles are running.
            reliability.report_heartbeat(component, now)
        try:
            reliability.report_resource_usage(now)
        except Exception:  # noqa: BLE001 -- resource sampling must never crash the loop
            logger.exception("resource usage sampling failed")
        queue_depth = command_queue.pending_count()
        try:
            reliability.report_queue_depth("bridge_command_queue", queue_depth, now)
        except Exception:  # noqa: BLE001
            logger.exception("failed to report queue depth")
        try:
            _write_health_snapshot(state_dir, reliability, bridge_engine, bridge_host, bridge_port, queue_depth)
        except Exception:  # noqa: BLE001
            logger.exception("failed to write health.json")
        _shutdown_event.wait(_HEARTBEAT_INTERVAL_SECONDS)


def run_foreground(config_path: Path) -> int:
    """The actual long-running process -- what `python start.py
    --foreground` (and, internally, `python start.py`) runs."""
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED: configuration error: {exc}", file=sys.stderr)
        return 2

    _setup_logging(settings.log_dir, settings.log_level)
    logger = logging.getLogger("titan_protocol.deploy")

    try:
        pid_file = _write_pid_file(settings.state_dir)
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2

    logger.info("Titan Protocol deployment layer starting (pid=%s, config=%s)", os.getpid(), config_path)

    strategy_config = StrategyEngineConfig()
    if settings.selected_profile == "custom":
        print(
            "FAILED: selected_profile is 'custom' -- a custom TradingProfile "
            "cannot be built from the config file alone (it needs an explicit "
            "allowed_pairs/allowed_strategies list). Edit this script's "
            "run_foreground() to call titan_protocol.runtime.profiles.make_custom_profile(...) directly.",
            file=sys.stderr,
        )
        return 2
    profile = _PROFILE_FACTORIES[settings.selected_profile]()
    validation_result = validate_profile(profile, strategy_config, settings.compliance_config)
    if not validation_result.valid:
        logger.error("Trading profile %s failed validation: %s", profile.profile_id, validation_result.issues)
        print(f"FAILED: trading profile validation failed: {validation_result.issues}", file=sys.stderr)
        return 2
    logger.info("Trading profile %s validated OK", profile.profile_id)

    command_queue = CommandQueue(settings.bridge_config)
    connection_health = ConnectionHealth(settings.bridge_config, _utc_now)
    bridge_engine = BridgeEngine(settings.bridge_config, command_queue, connection_health, _utc_now)
    try:
        http_server = bridge_serve(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=settings.bridge_port)
    except OSError as exc:
        logger.error("Bridge HTTP server failed to bind %s:%s -- %s", settings.bridge_host, settings.bridge_port, exc)
        print(f"FAILED: Bridge could not bind {settings.bridge_host}:{settings.bridge_port}: {exc}", file=sys.stderr)
        return 2
    server_thread = threading.Thread(target=http_server.serve_forever, name="titan_protocol-bridge-http", daemon=True)
    server_thread.start()
    logger.info("Bridge HTTP service listening on %s:%s", settings.bridge_host, settings.bridge_port)

    evidence_engine = EvidenceEngine(EvidenceEngineConfig())
    market_intelligence_engine = MarketIntelligenceEngine(settings.news_config)
    strategy_engine = StrategyEngine(strategy_config)
    risk_engine = RiskEngine(settings.risk_config)
    compliance_engine = ComplianceEngine(settings.compliance_config)

    def bridge_submit(command, now):
        return bridge_engine.submit_command(command, now)

    orchestrator = RuntimeOrchestrator(
        settings.runtime_config, evidence_engine, market_intelligence_engine,
        strategy_engine, risk_engine, compliance_engine, bridge_submit,
    )
    logger.info("RuntimeOrchestrator constructed (cycle loop NOT started -- see KNOWN_GAPS.md)")
    del orchestrator

    reliability = ReliabilityEngine(settings.reliability_config)
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, args=(reliability, bridge_engine, command_queue, settings.state_dir, settings.bridge_host, settings.bridge_port),
        name="titan_protocol-reliability-heartbeat", daemon=True,
    )
    heartbeat_thread.start()

    def _handle_shutdown(signum, _frame):
        logger.info("Received signal %s -- shutting down", signum)
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    print("=" * 72)
    print("TITAN_PROTOCOL DEPLOYMENT LAYER -- STATUS: DEGRADED")
    print(f"  Bridge HTTP service : LIVE on {settings.bridge_host}:{settings.bridge_port}")
    print(f"  Trading profile      : {profile.profile_id} (validated OK)")
    print("  5 core engines       : constructed OK")
    print("  Reliability monitor  : running (process-liveness + Bridge/MT5 heartbeats)")
    print("  LIVE TRADING CYCLE   : NOT ACTIVE -- no market-data ingestion")
    print("                          component is wired into this entry point.")
    print("                          See KNOWN_GAPS.md before relying on this")
    print("                          for real trading.")
    print("=" * 72)
    logger.warning("STATUS=DEGRADED -- Bridge+Reliability running; trading cycle loop is NOT active (see KNOWN_GAPS.md)")

    try:
        while not _shutdown_event.is_set():
            time.sleep(1.0)
    finally:
        logger.info("Stopping Bridge HTTP server")
        http_server.shutdown()
        http_server.server_close()
        try:
            pid_file.unlink()
        except OSError:
            pass
        logger.info("Titan Protocol deployment layer stopped cleanly")

    return 0


def _existing_pid(state_dir: Path) -> "int | None":
    pid_file = state_dir / "titan_protocol.pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        return None


def launch_and_report(config_path: Path) -> int:
    """Default mode: spawn `--foreground` as a detached child process,
    wait, health-check it, print HEALTHY/DEGRADED/FAILED, return."""
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED: configuration error: {exc}", file=sys.stderr)
        return 2

    existing_pid = _existing_pid(settings.state_dir)
    if existing_pid is not None:
        print(f"Titan Protocol already appears to be running (pid {existing_pid}).")
        print("Run health_check.py to check its status, or stop.py to stop it first.")
        return _run_health_check(config_path)

    python_exe = str(_venv_python()) if _venv_python().exists() else sys.executable
    creation_flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    print("Starting Titan Protocol in a new background process...")
    subprocess.Popen(
        [python_exe, str(_HERE / "start.py"), "--foreground", "--config", str(config_path)],
        cwd=str(_HERE), creationflags=creation_flags,
        stdout=None if os.name == "nt" else subprocess.DEVNULL,
        stderr=None if os.name == "nt" else subprocess.DEVNULL,
        start_new_session=(os.name != "nt"),
    )

    print("Waiting for startup to settle...")
    time.sleep(5.0)

    print()
    print("=" * 60)
    print("Titan Protocol health check")
    print("=" * 60)
    return _run_health_check(config_path)


def _run_health_check(config_path: Path) -> int:
    import health_check

    exit_code = health_check.run(config_path)
    if exit_code == 0:
        print("STATUS: HEALTHY")
    elif exit_code == 1:
        print("STATUS: DEGRADED")
    else:
        print("STATUS: FAILED")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Titan Protocol live runtime launcher")
    parser.add_argument("--config", default=str(_HERE / "titan_protocol_config.json"))
    parser.add_argument("--foreground", action="store_true", help="run as the actual long-lived process (used internally)")
    args = parser.parse_args()

    _check_running_under_venv()

    config_path = Path(args.config)
    if args.foreground:
        return run_foreground(config_path)
    return launch_and_report(config_path)


if __name__ == "__main__":
    raise SystemExit(main())
