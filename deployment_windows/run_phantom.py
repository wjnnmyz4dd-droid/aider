"""Phantom live runtime entry point (Windows deployment layer).

HONESTY NOTE -- read before assuming this starts live trading:

This script wires together every engine's REAL, existing, public
constructor exactly as the phantom/ test suite and
PHANTOM_MT5_DEPLOYMENT_AUDIT.md's own Runtime Startup Order describe --
it introduces zero new trading logic, zero new engine behavior, and no
architectural redesign. What it starts:

  1. The Bridge HTTP service (phantom.bridge.server.serve) -- the real,
     exported, public function the EA's WebRequest calls target.
  2. The five core trading engines (Evidence, Market Intelligence,
     Strategy, Risk, Compliance) and the Runtime Orchestrator wired to
     them, per phantom/runtime/engine.py's real constructor signature.
  3. The Reliability Engine, self-monitoring this process's own
     liveness and the Bridge's reachability.

What it deliberately does NOT do, and will not silently pretend to do:
Phantom's `RuntimeOrchestrator.run_cycle()` requires live bars, news
events, spreads, portfolio state, and account state to be supplied by
the CALLER for every cycle. Nothing in the minimum live deployment
package (confirmed by import-tracing every file in phantom/bridge and
phantom/runtime) fetches that data from MT5 or any market-data
provider -- the Bridge's own protocol (heartbeat/account/positions/
orders/trade-transaction/error/execution-report/commands-poll) is
entirely about EXECUTION, never market data. The shipped MT5 EA
self-documents itself as "transport + execution bridge ONLY: it never
generates, scores, or [fetches market data]."

Building a live trading cycle loop would therefore require inventing a
brand-new market-data-ingestion component -- a new architectural
capability with no Accepted ADR behind it. Per this deployment
mission's own instruction ("do not silently invent a runtime entry
point... stop and report the exact missing wiring instead of creating
business logic"), this script does NOT fabricate one. See
KNOWN_GAPS.md in this same folder for the precise, actionable gap.

This script's own exit status and printed banner make the above
unmistakable every time it runs -- it never claims a status it hasn't
actually achieved.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so `import phantom` works

from phantom.bridge.command_queue import CommandQueue
from phantom.bridge.connection_health import ConnectionHealth
from phantom.bridge.engine import BridgeEngine
from phantom.bridge.server import serve as bridge_serve
from phantom.compliance_engine.engine import ComplianceEngine
from phantom.evidence_engine.config import EvidenceEngineConfig
from phantom.evidence_engine.engine import EvidenceEngine
from phantom.market_intelligence.engine import MarketIntelligenceEngine
from phantom.reliability.engine import ReliabilityEngine
from phantom.risk_engine.engine import RiskEngine
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.validation import validate_profile
from phantom.runtime import profiles as trading_profiles
from phantom.strategy_engine.config import StrategyEngineConfig
from phantom.strategy_engine.engine import StrategyEngine

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
        log_dir / f"phantom_{timestamp}.log", maxBytes=25 * 1024 * 1024, backupCount=10, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def _write_pid_file(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_file = state_dir / "phantom.pid"
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text().strip())
            os.kill(existing_pid, 0)  # raises OSError if no such process (Windows: works via ctypes-backed impl)
            raise RuntimeError(
                f"Phantom already appears to be running (pid {existing_pid} in {pid_file}). "
                "Refusing to start a second instance -- run stop_phantom.bat first if that pid is stale."
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


def _write_health_snapshot(state_dir: Path, reliability: ReliabilityEngine, bridge_host: str, bridge_port: int) -> None:
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
        "cycle_loop_active": False,
        "cycle_loop_inactive_reason": (
            "No market-data ingestion component exists in this deployment package -- "
            "see KNOWN_GAPS.md. Bridge (execution channel) and Reliability (this health "
            "monitor) are live; the trading decision cycle is not."
        ),
    }
    (state_dir / "health.json").write_text(json.dumps(payload, indent=2))


def _heartbeat_loop(reliability: ReliabilityEngine, state_dir: Path, bridge_host: str, bridge_port: int) -> None:
    logger = logging.getLogger("phantom.deploy.heartbeat")
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
        try:
            _write_health_snapshot(state_dir, reliability, bridge_host, bridge_port)
        except Exception:  # noqa: BLE001
            logger.exception("failed to write health.json")
        _shutdown_event.wait(_HEARTBEAT_INTERVAL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phantom live runtime entry point")
    parser.add_argument("--config", default=str(Path(__file__).parent / "phantom.config.ini"))
    args = parser.parse_args()

    config_path = Path(args.config)
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED: configuration error: {exc}", file=sys.stderr)
        return 2

    _setup_logging(settings.log_dir, settings.log_level)
    logger = logging.getLogger("phantom.deploy")

    try:
        pid_file = _write_pid_file(settings.state_dir)
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2

    logger.info("Phantom deployment layer starting (pid=%s, config=%s)", os.getpid(), config_path)

    # -- Trading profile: construct + validate before anything else starts.
    strategy_config = StrategyEngineConfig()
    if settings.selected_profile == "custom":
        print(
            "FAILED: selected_profile is 'custom' -- a custom TradingProfile "
            "cannot be built from the config file alone (it needs an explicit "
            "allowed_pairs/allowed_strategies list). Edit this script's main() "
            "to call phantom.runtime.profiles.make_custom_profile(...) directly.",
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

    # -- Bridge: real, existing public interfaces only.
    command_queue = CommandQueue(settings.bridge_config)
    connection_health = ConnectionHealth(settings.bridge_config, _utc_now)
    bridge_engine = BridgeEngine(settings.bridge_config, command_queue, connection_health, _utc_now)
    try:
        http_server = bridge_serve(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=settings.bridge_port)
    except OSError as exc:
        logger.error("Bridge HTTP server failed to bind %s:%s -- %s", settings.bridge_host, settings.bridge_port, exc)
        print(f"FAILED: Bridge could not bind {settings.bridge_host}:{settings.bridge_port}: {exc}", file=sys.stderr)
        return 2
    server_thread = threading.Thread(target=http_server.serve_forever, name="phantom-bridge-http", daemon=True)
    server_thread.start()
    logger.info("Bridge HTTP service listening on %s:%s", settings.bridge_host, settings.bridge_port)

    # -- The five core engines + Runtime Orchestrator (constructed and
    # ready; see module docstring -- no live cycle loop is started).
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
    logger.info("RuntimeOrchestrator constructed (engine_versions ready; cycle loop NOT started -- see KNOWN_GAPS.md)")
    del orchestrator  # constructed to prove wiring compiles/works; not driven, per this script's own honesty note

    # -- Reliability: self-monitoring this process + Bridge reachability.
    reliability = ReliabilityEngine(settings.reliability_config)
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, args=(reliability, settings.state_dir, settings.bridge_host, settings.bridge_port),
        name="phantom-reliability-heartbeat", daemon=True,
    )
    heartbeat_thread.start()

    def _handle_shutdown(signum, _frame):
        logger.info("Received signal %s -- shutting down", signum)
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    print("=" * 72)
    print("PHANTOM DEPLOYMENT LAYER -- STATUS: DEGRADED")
    print(f"  Bridge HTTP service : LIVE on {settings.bridge_host}:{settings.bridge_port}")
    print(f"  Trading profile      : {profile.profile_id} (validated OK)")
    print("  5 core engines       : constructed OK")
    print("  Reliability monitor  : running (process-liveness heartbeats)")
    print("  LIVE TRADING CYCLE   : NOT ACTIVE -- no market-data ingestion")
    print("                          component exists in this deployment.")
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
        logger.info("Phantom deployment layer stopped cleanly")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
