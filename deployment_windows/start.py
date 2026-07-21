"""Titan Protocol live runtime launcher (Python Deployment Manager).

HONESTY NOTE -- read before assuming this starts live trading:

This script wires together every engine's REAL, existing, public
constructor exactly as the titan_protocol/ test suite and
PHANTOM_MT5_DEPLOYMENT_AUDIT.md's own Runtime Startup Order describe --
it introduces zero new trading logic, zero new engine behavior, and no
architectural redesign. What it starts:

  1. The Bridge (titan_protocol.bridge.server.serve /
     titan_protocol.bridge.socket_transport.serve_socket) -- HTTP
     transport by default (ADR-034 Amendment 4), with the native socket
     transport fully supported as an explicit opt-in (bridge.transport
     ="socket"); an automatic HTTP fallback listener is also bound
     whenever transport is socket (ADR-034 Amendment 3), so an EA that
     falls back to HTTP client-side is still reachable.
  2. The five core trading engines (Evidence, Market Intelligence,
     Strategy, Risk, Compliance) and the Runtime Orchestrator wired to
     them, per titan_protocol/runtime/engine.py's real constructor signature.
  3. The Reliability Engine, self-monitoring this process's own
     liveness, the Bridge's reachability, and -- via
     BridgeEngine.is_connection_healthy -- whether the MT5 EA has
     actually heartbeated recently (not just whether the port is open).

Amendment 1 (ADR-023) update: `RuntimeOrchestrator.run_cycle()` now
receives real, live-sourced bars/spread on a real schedule (see
`_live_cycle_loop()`), fed by `titan_protocol/bridge/`'s new
`/bridge/market-data` endpoint through the existing, unmodified
`MarketDataIngestionEngine` (ADR-033). It is called only when that
engine's own `is_ready()` says the feed for a pair is warmed-up and
fresh -- never with fabricated data, and a pair with no data yet is
simply skipped for that tick (see health.json's `live_cycle` field).

Phase 3E (ADR-033 Part 2) update: `events` is now real, dual-provider
news (Trading Economics primary, Forex Factory backup, via the new,
unmodified-by-anything-else `NewsIngestionEngine`) -- refreshed on its
own slower cadence (see `_NEWS_REFRESH_INTERVAL_SECONDS`) and, when both
providers are down, the live-cycle loop skips *every* pair for that tick
(`market_intelligence_not_ready`) rather than passing stale or empty
events through silently. Market Intelligence Engine itself is
unmodified and never knows which provider produced its events.

Final Release Hardening update: `daily_starting_balance`, `peak_balance`
(the total-drawdown reference), `compliance_lock`, and the active
trading-day identifier are now restart-safe -- persisted via
`titan_protocol.compliance_state_store` (a narrowly-scoped, caller-owned
state store; `ComplianceEngine` itself remains stateless and unmodified,
see `_build_compliance_account_state()`). "Current daily loss" and
"daily profit state" are deliberately NOT persisted separately: they
are already derived live by the engine's own `daily_loss.py`/
`profit_protection.py` from `account_balance` vs `daily_starting_balance`
-- storing them again would duplicate a calculation the engine already
owns. `portfolio_state`/`trade_history` still use safe, empty defaults
(auto-converting EA-reported position/order state into a fully-tracked
portfolio model remains out of scope -- see KNOWN_GAPS.md). This script
reports its real status -- **DEGRADED, never HEALTHY** -- both
on-screen and in state/health.json, and never claims otherwise.

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
from typing import Dict, Optional, Sequence, Tuple

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
from titan_protocol.bridge.metrics import BridgeMetrics
from titan_protocol.bridge.models import PositionDirection, PositionReport
from titan_protocol.bridge.server import serve as bridge_serve
from titan_protocol.bridge.socket_transport import serve_socket as bridge_serve_socket
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import AccountState as ComplianceAccountState
from titan_protocol.compliance_state_store.config import ComplianceStateStoreConfig
from titan_protocol.compliance_state_store.models import CorruptStateError, PersistedComplianceState
from titan_protocol.compliance_state_store.store import ComplianceStateStore
from titan_protocol.compliance_state_store.store import to_account_state as _compliance_state_to_account_state
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.market_data_ingestion.config import MarketDataIngestionConfig
from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.metrics import MarketDataIngestionMetrics
from titan_protocol.market_data_ingestion.models import Timeframe as IngestionTimeframe
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs
from titan_protocol.news_ingestion.config import NewsIngestionConfig
from titan_protocol.news_ingestion.engine import NewsIngestionEngine
from titan_protocol.news_ingestion.metrics import NewsIngestionMetrics
from titan_protocol.news_ingestion.models import ProviderName
from titan_protocol.news_ingestion.providers.forex_factory import ForexFactoryProvider
from titan_protocol.news_ingestion.providers.trading_economics import TradingEconomicsProvider
from titan_protocol.reliability.engine import ReliabilityEngine
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import Direction, OpenPosition, PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.in_flight_commands import InFlightCommandRegistry
from titan_protocol.runtime.metrics import RuntimeMetrics
from titan_protocol.runtime.models import CycleOutcome
from titan_protocol.runtime.validation import validate_profile
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.engine import StrategyEngine

from config_loader import ConfigError, build_trading_profile, is_process_alive, load_settings

_HEARTBEAT_INTERVAL_SECONDS = 5.0
_RESTARTABLE_ENGINES = ("evidence_engine", "market_intelligence", "strategy_engine", "risk_engine")

# Amendment 1 (ADR-023) -- live-cycle loop constants.
_LIVE_CYCLE_INTERVAL_SECONDS = 15.0
# In-flight command guard TTL -- how long RuntimeOrchestrator waits for a
# submitted command's ExecutionReport before allowing a new submission
# for the same pair regardless (bounds a lost/never-arriving report, same
# reasoning as CommandQueue's own correlation_ttl_seconds, just scoped to
# this decision-time gate rather than the relay's own memory). 20x the
# live-cycle interval -- long enough to absorb normal execution latency
# and a few missed heartbeat cycles, short enough to recover within
# minutes rather than hours if a report is genuinely lost.
_IN_FLIGHT_COMMAND_TTL_SECONDS = _LIVE_CYCLE_INTERVAL_SECONDS * 20
# Runtime takes exactly one bar sequence per pair per cycle (Evidence
# Engine's own single-timeframe design) -- M15 is this deployment's
# primary timeframe, matching every trading profile's own granularity.
_PRIMARY_TIMEFRAME = IngestionTimeframe.M15

# Phase 3E (ADR-033 Part 2) -- news providers are polled far less often
# than the 15s trading cycle: an economic calendar changes on the order
# of minutes, not seconds, and real providers rate-limit aggressive
# polling. The live-cycle loop reuses its last fetched (events, trusted)
# result between refreshes rather than re-fetching every tick.
_NEWS_REFRESH_INTERVAL_SECONDS = 300.0

_shutdown_event = threading.Event()


class _LiveCycleStatus:
    """Shared, lock-protected holder the live-cycle loop writes to and
    `_write_health_snapshot` reads from -- avoids two threads writing
    health.json at once. Observability only; never a decision input."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = False
        self.last_cycle_at: Optional[datetime] = None
        self.last_cycle_id: Optional[str] = None
        self.evaluated_pairs: Tuple[str, ...] = ()
        self.skipped_pairs: Dict[str, str] = {}
        # Run Status diagnostics (item 10): compliance-lock state and a
        # per-pair decision summary (outcome/reason/correlation_id/
        # compliance_decision), merging pre-engine skip reasons with
        # run_cycle()'s own per-pair RuntimeAuditRecord -- both are
        # computed every cycle in _live_cycle_loop and would otherwise be
        # visible only in scattered log lines. Observability only.
        self.compliance_lock_active: bool = False
        self.compliance_lock_reason: Optional[str] = None
        self.pair_status: Dict[str, dict] = {}
        self.last_submitted_correlation_id: Optional[str] = None

    def update(self, now: datetime, cycle_id: str, evaluated_pairs, skipped_pairs: Dict[str, str]) -> None:
        with self._lock:
            self.active = True
            self.last_cycle_at = now
            self.last_cycle_id = cycle_id
            self.evaluated_pairs = tuple(evaluated_pairs)
            self.skipped_pairs = dict(skipped_pairs)

    def update_decisions(
        self, compliance_lock_active: bool, compliance_lock_reason: Optional[str],
        pair_status: Dict[str, dict], last_submitted_correlation_id: Optional[str],
    ) -> None:
        with self._lock:
            self.compliance_lock_active = compliance_lock_active
            self.compliance_lock_reason = compliance_lock_reason
            self.pair_status = dict(pair_status)
            if last_submitted_correlation_id is not None:
                self.last_submitted_correlation_id = last_submitted_correlation_id

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "active": self.active,
                "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
                "last_cycle_id": self.last_cycle_id,
                "evaluated_pairs": list(self.evaluated_pairs),
                "skipped_pairs": dict(self.skipped_pairs),
                "compliance_lock_active": self.compliance_lock_active,
                "compliance_lock_reason": self.compliance_lock_reason,
                "pair_status": dict(self.pair_status),
                "last_submitted_correlation_id": self.last_submitted_correlation_id,
            }


_live_cycle_status = _LiveCycleStatus()


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


def _market_data_health_payload(market_data_engine: Optional[MarketDataIngestionEngine], market_data_metrics: Optional[MarketDataIngestionMetrics], now: datetime) -> Optional[dict]:
    """Amendment 1 (ADR-023) -- exposes `MarketDataIngestionEngine`'s
    own existing health/metrics objects verbatim. No new metric is
    computed here; `MarketDataIngestionMetrics` does not track
    ingestion latency, so it is honestly omitted rather than
    approximated."""
    if market_data_engine is None:
        return None
    snapshot = market_data_engine.health_snapshot(now)
    payload = {
        "warmup_statuses": [
            {"symbol": s.symbol, "timeframe": s.timeframe.value, "bars_received": s.bars_received, "bars_required": s.bars_required, "ready": s.ready}
            for s in snapshot.warmup_statuses
        ],
        "freshness": [
            {
                "symbol": f.symbol, "timeframe": f.timeframe.value,
                "last_bar_open_time": f.last_bar_open_time.isoformat() if f.last_bar_open_time else None,
                "is_stale": f.is_stale,
            }
            for f in snapshot.freshness
        ],
        "recent_gap_reasons": list(snapshot.reasons),
    }
    if market_data_metrics is not None:
        payload["metrics"] = {
            "bars_accepted": market_data_metrics.accepted_count,
            "bars_rejected": market_data_metrics.rejected_count,
            "gaps_detected": market_data_metrics.gaps_detected_count,
            "ticks_ingested": market_data_metrics.ticks_ingested_count,
        }
    return payload


def _news_health_payload(news_engine: Optional[NewsIngestionEngine], news_metrics: Optional[NewsIngestionMetrics], now: datetime) -> Optional[dict]:
    """Phase 3E (ADR-033 Part 2) -- exposes `NewsIngestionEngine`'s own
    existing health snapshot verbatim (active provider, per-provider
    health, failover/recovery counts) plus `NewsIngestionMetrics`'
    per-provider fetch counters. No new metric is computed here."""
    if news_engine is None:
        return None
    snapshot = news_engine.health_snapshot(now)
    payload = {
        "active_provider": snapshot.active_provider.value,
        "trusted": snapshot.trusted,
        "provider_health": [
            {
                "provider": h.provider.value, "trust_state": h.trust_state.value,
                "last_success_at": h.last_success_at.isoformat() if h.last_success_at else None,
                "latency_ms": h.latency_ms, "timeout_count": h.timeout_count,
                "parse_failure_count": h.parse_failure_count,
                "consecutive_successes": h.consecutive_successes,
                "stale_age_seconds": h.stale_age_seconds, "last_error": h.last_error,
            }
            for h in snapshot.provider_health
        ],
        "failover_state": {
            "active_provider": snapshot.failover_state.active_provider.value,
            "failover_count": snapshot.failover_state.failover_count,
            "recovery_count": snapshot.failover_state.recovery_count,
            "last_failover_at": snapshot.failover_state.last_failover_at.isoformat() if snapshot.failover_state.last_failover_at else None,
            "last_recovery_at": snapshot.failover_state.last_recovery_at.isoformat() if snapshot.failover_state.last_recovery_at else None,
        },
    }
    if news_metrics is not None:
        payload["metrics"] = {
            "dual_outage_count": news_metrics.dual_outage_count,
            "fetch_successes": {p.value: news_metrics.fetch_success_count(p) for p in ProviderName},
            "fetch_failures": {p.value: news_metrics.fetch_failure_count(p) for p in ProviderName},
        }
    return payload


def _write_health_snapshot(
    state_dir: Path, reliability: ReliabilityEngine, bridge_engine: BridgeEngine, bridge_host: str, bridge_port: int, queue_depth: int,
    market_data_engine: Optional[MarketDataIngestionEngine] = None,
    market_data_metrics: Optional[MarketDataIngestionMetrics] = None,
    runtime_metrics: Optional[RuntimeMetrics] = None,
    news_engine: Optional[NewsIngestionEngine] = None,
    news_metrics: Optional[NewsIngestionMetrics] = None,
    bridge_transport: Optional[str] = None,
    bridge_metrics: Optional[BridgeMetrics] = None,
    connection_health: Optional[ConnectionHealth] = None,
    in_flight_commands: Optional[InFlightCommandRegistry] = None,
    http_fallback_active: bool = False,
    configured_max_positions_per_pair: Optional[int] = None,
    configured_max_account_state_age_seconds: Optional[float] = None,
) -> None:
    now = _utc_now()
    snapshot = reliability.evaluate_health(now)
    live_cycle = _live_cycle_status.snapshot()
    last_heartbeat_at = connection_health.last_heartbeat_at if connection_health is not None else None
    latest_positions_snapshot_at = bridge_engine.last_positions_received_at
    # Run Status diagnostics (item 10): every field an operator needs to
    # answer "why is Titan trading or not" from this one block, without
    # cross-referencing bridge_reachable/mt5_connected/live_cycle/etc
    # separately or grepping the log file. Every value here is read from
    # an object this process already holds a reference to -- no new
    # computation, only surfacing what already exists.
    open_positions_per_pair: Dict[str, int] = {}
    for position in bridge_engine.latest_positions:
        open_positions_per_pair[position.symbol] = open_positions_per_pair.get(position.symbol, 0) + 1
    # ACCOUNT_STATE_STALE diagnostics: independently recomputed here from
    # BridgeEngine.latest_account_state.received_at -- the same source
    # _build_compliance_account_state() reads in the live-cycle thread --
    # so an operator can see account-state freshness even on a cycle
    # where account_state was None (never reported) or the account gate
    # itself never ran (e.g. an earlier pre-engine skip already applied).
    latest_account_state = bridge_engine.latest_account_state
    account_report_age_seconds = (
        (now - latest_account_state.received_at).total_seconds() if latest_account_state is not None else None
    )
    account_state_fresh = (
        account_report_age_seconds <= configured_max_account_state_age_seconds
        if account_report_age_seconds is not None and configured_max_account_state_age_seconds is not None
        else None
    )
    run_status = {
        "communication_mode": bridge_transport,
        "http_fallback_enabled": http_fallback_active,
        "bridge_connection_status": "connected" if bridge_engine.is_connection_healthy else "disconnected",
        "runtime_status": snapshot.degradation_level.value,
        "last_heartbeat_age_seconds": (now - last_heartbeat_at).total_seconds() if last_heartbeat_at else None,
        "last_position_report_age_seconds": (
            (now - latest_positions_snapshot_at).total_seconds() if latest_positions_snapshot_at else None
        ),
        "in_flight_command_count": in_flight_commands.in_flight_count() if in_flight_commands is not None else None,
        "open_positions_per_pair": open_positions_per_pair,
        "configured_max_positions_per_pair": configured_max_positions_per_pair,
        "account_report_age_seconds": account_report_age_seconds,
        "configured_max_account_state_age_seconds": configured_max_account_state_age_seconds,
        "account_state_fresh": account_state_fresh,
        "compliance_state": "BLOCKED" if live_cycle["compliance_lock_active"] else "READY",
        "compliance_block_reason": live_cycle["compliance_lock_reason"],
        "last_submitted_correlation_id": live_cycle["last_submitted_correlation_id"],
        "pairs": live_cycle["pair_status"],
    }
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
        # Amendment 1 (ADR-023): the loop itself is active whenever this
        # process constructed it -- individual pairs may still be
        # skipped per-tick (see live_cycle.skipped_pairs) when their
        # market data isn't ready. "Active" here mirrors "reliability
        # monitor alive"'s own meaning: the loop is running, not that
        # every pair traded this tick.
        "cycle_loop_active": live_cycle["active"],
        "live_cycle": live_cycle,
        "market_data": _market_data_health_payload(market_data_engine, market_data_metrics, now),
        "news": _news_health_payload(news_engine, news_metrics, now),
        "runtime_cycle_counts": (
            {"cycle_count": runtime_metrics.cycle_count, "failure_count": runtime_metrics.failure_count}
            if runtime_metrics is not None else None
        ),
        # ADR-034 -- detailed socket-transport health, only meaningful
        # (and only ever non-None) when bridge.transport=="socket".
        "bridge_transport": bridge_transport,
        "bridge_socket": (
            bridge_metrics.socket_health_snapshot()
            if bridge_metrics is not None and bridge_transport == "socket" else None
        ),
        "run_status": run_status,
    }
    (state_dir / "health.json").write_text(json.dumps(payload, indent=2))


def _heartbeat_loop(
    reliability: ReliabilityEngine, bridge_engine: BridgeEngine, command_queue: CommandQueue, state_dir: Path, bridge_host: str, bridge_port: int,
    market_data_engine: Optional[MarketDataIngestionEngine] = None,
    market_data_metrics: Optional[MarketDataIngestionMetrics] = None,
    runtime_metrics: Optional[RuntimeMetrics] = None,
    news_engine: Optional[NewsIngestionEngine] = None,
    news_metrics: Optional[NewsIngestionMetrics] = None,
    bridge_transport: Optional[str] = None,
    bridge_metrics: Optional[BridgeMetrics] = None,
    connection_health: Optional[ConnectionHealth] = None,
    in_flight_commands: Optional[InFlightCommandRegistry] = None,
    http_fallback_active: bool = False,
    configured_max_positions_per_pair: Optional[int] = None,
    configured_max_account_state_age_seconds: Optional[float] = None,
) -> None:
    logger = logging.getLogger("titan_protocol.deploy.heartbeat")
    while not _shutdown_event.is_set():
        now = _utc_now()
        for component in _RESTARTABLE_ENGINES:
            # Process-liveness heartbeat: this process is alive and these
            # engine objects were constructed and remain importable/usable.
            # This is NOT a trade-cycle heartbeat -- the live-cycle loop
            # (a separate thread) reports its own activity via health.json's
            # live_cycle/cycle_loop_active fields instead.
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
            _write_health_snapshot(
                state_dir, reliability, bridge_engine, bridge_host, bridge_port, queue_depth,
                market_data_engine, market_data_metrics, runtime_metrics, news_engine, news_metrics,
                bridge_transport=bridge_transport, bridge_metrics=bridge_metrics,
                connection_health=connection_health, in_flight_commands=in_flight_commands,
                http_fallback_active=http_fallback_active,
                configured_max_positions_per_pair=configured_max_positions_per_pair,
                configured_max_account_state_age_seconds=configured_max_account_state_age_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to write health.json")
        _shutdown_event.wait(_HEARTBEAT_INTERVAL_SECONDS)


def _build_compliance_account_state(
    bridge_engine: BridgeEngine,
    compliance_state_store: ComplianceStateStore,
    persisted_state: Optional[PersistedComplianceState],
    now: datetime,
) -> Tuple[Optional[ComplianceAccountState], Optional[PersistedComplianceState]]:
    """Amendment 1 (ADR-023) + Final Release Hardening -- maps the
    EA-reported balance (already flowing in via the existing,
    unmodified `/bridge/account` endpoint) onto
    `compliance_engine.models.AccountState`'s required fields, using
    restart-safe `daily_starting_balance`/`peak_balance`/
    `compliance_lock` loaded from `compliance_state_store` rather than
    hardcoded per-cycle defaults.

    Returns `(None, persisted_state)` (caller skips the cycle) if the
    EA has not reported account state yet -- day-state is only ever
    bootstrapped or reconciled once a real balance is available, never
    guessed.

    Also threads `account_report_age_seconds` (seconds since `latest`
    was received) onto the returned `AccountState`, so
    `ComplianceEngine.evaluate()` can reject new entries with
    `ACCOUNT_STATE_STALE` if this balance is too old to trust for
    daily-loss/drawdown -- rather than silently evaluating those curves
    against a frozen snapshot that may no longer reflect reality."""

    latest = bridge_engine.latest_account_state
    if latest is None:
        return None, persisted_state
    if persisted_state is None:
        persisted_state = compliance_state_store.load_or_bootstrap(now, latest.balance)
    persisted_state = compliance_state_store.reconcile(persisted_state, now, latest.balance)
    account_report_age_seconds = (now - latest.received_at).total_seconds()
    account_state = _compliance_state_to_account_state(
        persisted_state, latest.balance, account_report_age_seconds=account_report_age_seconds,
    )
    return account_state, persisted_state


_POSITION_DIRECTION_TO_RISK_DIRECTION = {
    PositionDirection.BUY: Direction.LONG,
    PositionDirection.SELL: Direction.SHORT,
}


def _map_bridge_positions_to_open_positions(
    positions: Sequence[PositionReport],
) -> Tuple[OpenPosition, ...]:
    """Adapter: BridgeEngine.latest_positions (EA-reported PositionReport,
    the Bridge transport shape) -> risk_engine.models.OpenPosition (the
    portfolio-state shape check_position_limits()/compute_exposure_summary()/
    check_safety_limits()/compute_correlation_status() all consume). Never
    passes a bridge model into the risk engine directly.

    KNOWN GAP (see deployment_windows/KNOWN_GAPS.md): OpenPosition.size_r is
    risk allocated to the position *in R* -- a risk-normalized unit.
    Deriving it from PositionReport's volume/open_price/stop_loss would
    require the account's risk-per-R at the time the position was opened,
    which this wire message does not carry and no existing module in this
    repo computes from raw volume alone. Fabricating a number here would
    inject an unverified value into real capital-preservation gates
    (compute_exposure_summary/check_safety_limits/compute_correlation_status)
    -- worse than the previous gap (an always-empty PortfolioState), not
    better. size_r is therefore fixed at 0.0: every mapped position still
    *exists* for count-based gating (check_position_limits() reads only
    `pair`) -- the defect this function closes -- while exposure/
    correlation/safety-limit math remains exactly as blind to already-open
    risk as it was before this change (no regression, not yet a full fix).

    opened_at is similarly not carried by PositionReport (only
    received_at -- when this position was last *reported*, not when it was
    opened). Using received_at is a documented approximation.

    Malformed records (missing symbol, unrecognized direction) are skipped
    individually and logged -- never silently dropped without a trace,
    never allowed to crash the whole batch."""
    logger = logging.getLogger("titan_protocol.deploy.live_cycle")
    mapped = []
    for position in positions:
        if not position.symbol:
            logger.warning(
                "skipping malformed position report -- missing symbol: position_id=%s",
                position.position_id,
            )
            continue
        direction = _POSITION_DIRECTION_TO_RISK_DIRECTION.get(position.direction)
        if direction is None:
            logger.warning(
                "skipping malformed position report -- unrecognized direction: "
                "position_id=%s symbol=%s direction=%r",
                position.position_id, position.symbol, position.direction,
            )
            continue
        mapped.append(
            OpenPosition(
                pair=position.symbol,
                direction=direction,
                size_r=0.0,  # KNOWN GAP -- see function docstring
                opened_at=position.received_at,  # approximation -- see function docstring
            )
        )
    return tuple(mapped)


def _live_cycle_loop(
    orchestrator: RuntimeOrchestrator,
    market_data_engine: MarketDataIngestionEngine,
    bridge_engine: BridgeEngine,
    profile,
    compliance_state_store: ComplianceStateStore,
    news_engine: Optional[NewsIngestionEngine] = None,
) -> None:
    """Amendment 1 (ADR-023) + Phase 3E (ADR-033 Part 2) + Final Release
    Hardening. Per pair, per tick: checks
    `MarketDataIngestionEngine.is_ready()` (already implemented, already
    checking warmup + staleness) and only calls
    `RuntimeOrchestrator.run_cycle_for_pair()` (unmodified) when ready.
    A pair with no ready market data, no reported spread yet, or no
    reported account state yet is skipped for this tick -- logged, never
    faked.

    Phase 3E adds the dual-provider news gate at this same call site
    (never inside Runtime, which has no `news_feed_trusted` passthrough
    of its own and is frozen for this phase): `news_engine.fetch_events()`
    is refreshed on its own, slower cadence
    (`_NEWS_REFRESH_INTERVAL_SECONDS`); when its most recent result is
    `trusted=False` (both providers down), *every* pair is skipped this
    tick with reason `market_intelligence_not_ready` -- the mission's own
    "No new trade decisions" fail-closed requirement -- before any other
    per-pair check runs. When trusted, the same real event tuple is
    passed to every ready pair; Market Intelligence Engine's own
    unmodified per-pair currency filtering (ADR-025 Hard Rule 2) narrows
    it down, exactly as `evaluate_batch()` already assumes.
    `market_safety_inputs`/`trade_history` use the safe, honest defaults
    every existing test fixture already uses for "no special condition".
    `portfolio_state` is built from `bridge_engine.latest_positions` via
    `_map_bridge_positions_to_open_positions()` (fixes: this was previously
    always `PortfolioState()`, empty, so `check_position_limits()` could
    never see an already-open position -- see KNOWN_GAPS.md for the
    residual `size_r`/`opened_at`/staleness approximations this adapter
    still carries).

    Final Release Hardening adds restart-safe day-state: `persisted_state`
    is loaded/bootstrapped once (on the first cycle a real balance is
    available) and reconciled every cycle thereafter via
    `compliance_state_store`, so `daily_starting_balance`/`peak_balance`/
    `compliance_lock` survive a Runtime/Python/MT5/VPS restart and reset
    only at the configured broker-time trading-day boundary."""

    logger = logging.getLogger("titan_protocol.deploy.live_cycle")
    cycle_number = 0
    news_events: tuple = ()
    news_trusted = True
    last_news_fetch_at: Optional[datetime] = None
    persisted_compliance_state: Optional[PersistedComplianceState] = None
    while not _shutdown_event.is_set():
        now = _utc_now()
        cycle_number += 1
        cycle_id = f"live-{cycle_number}"
        skipped: Dict[str, str] = {}
        inputs: Dict[str, tuple] = {}

        if news_engine is not None and (
            last_news_fetch_at is None
            or (now - last_news_fetch_at).total_seconds() >= _NEWS_REFRESH_INTERVAL_SECONDS
        ):
            try:
                news_events, news_trusted = news_engine.fetch_events(now)
            except Exception:  # noqa: BLE001 -- a news-fetch crash must never crash the live-cycle loop
                logger.exception("news_engine.fetch_events failed -- treating as untrusted this cycle")
                news_events, news_trusted = (), False
            last_news_fetch_at = now

        try:
            account_state, persisted_compliance_state = _build_compliance_account_state(
                bridge_engine, compliance_state_store, persisted_compliance_state, now,
            )
        except CorruptStateError:
            logger.critical(
                "persisted compliance state is corrupted/ambiguous -- failing closed, "
                "skipping every pair this cycle until an operator resolves it"
            )
            account_state = None

        # Run Status diagnostics (item 10): compliance-lock state is
        # already computed above (persisted_compliance_state), just not
        # previously retained anywhere health.json could read from.
        compliance_lock_active = (
            persisted_compliance_state.compliance_lock.active if persisted_compliance_state is not None else False
        )
        compliance_lock_reason = (
            persisted_compliance_state.compliance_lock.reason if persisted_compliance_state is not None else None
        )

        # Map real EA-reported positions into PortfolioState -- previously
        # this was PortfolioState() (always empty, no arguments), so
        # check_position_limits() could never see an already-open position
        # and reject a duplicate entry for the same pair. is_connection_healthy
        # (heartbeat-timeout-based) is the only freshness signal BridgeEngine
        # currently exposes; positions are reported in the same OnTimer batch
        # as heartbeat, so a healthy heartbeat is treated as grounds to trust
        # latest_positions as current -- including trusting an empty result
        # as "confirmed zero positions", not "never reported". This is a
        # proxy, not a proof -- see KNOWN_GAPS.md for the residual ambiguity
        # if /bridge/positions specifically fails while heartbeat keeps
        # succeeding.
        positions_are_live = bridge_engine.is_connection_healthy
        raw_positions: Tuple[PositionReport, ...] = bridge_engine.latest_positions if positions_are_live else ()
        open_positions = _map_bridge_positions_to_open_positions(raw_positions) if positions_are_live else ()
        if not positions_are_live:
            position_source_state = "absent"
        elif len(open_positions) != len(raw_positions):
            position_source_state = "invalid"
        else:
            position_source_state = "live"
        # BridgeEngine.last_positions_received_at is set unconditionally by
        # handle_positions(), including on an empty (all-closed) snapshot --
        # unlike deriving a timestamp from the position reports themselves
        # (max(p.received_at ...)), which has nothing to derive from when
        # the list is empty. Used both for observability here and as the
        # authoritative "was this snapshot taken after resolution" check in
        # confirm_position_report() below.
        latest_positions_snapshot_at = bridge_engine.last_positions_received_at
        position_report_age_seconds = (
            (now - latest_positions_snapshot_at).total_seconds() if latest_positions_snapshot_at else None
        )
        logger.info(
            "portfolio_state_source",
            extra={
                "bridge_position_count": len(raw_positions),
                "mapped_position_count": len(open_positions),
                "latest_position_report_at": latest_positions_snapshot_at.isoformat() if latest_positions_snapshot_at else None,
                "position_report_age_seconds": position_report_age_seconds,
                "position_source_state": position_source_state,
            },
        )

        # Reconcile the in-flight command registry against the Bridge's
        # own record of which correlation_ids have reached a terminal
        # state (BridgeEngine.command_resolved() -> CommandQueue.is_executed()),
        # dropping resolved-or-expired entries before this cycle's per-pair
        # gate runs (RuntimeOrchestrator.run_cycle_for_pair()'s
        # in_flight_commands.has_unresolved() check). A pair resolved via a
        # real ExecutionReport (not a TTL expiry) moves into
        # "awaiting position confirmation" rather than being fully cleared
        # -- confirm_position_report() below is the only thing that can
        # release it, closing the window where an ExecutionReport arrives
        # before the position it opened is visible in the next
        # /bridge/positions snapshot.
        resolved_count = orchestrator.in_flight_commands.reconcile(
            now, bridge_engine.command_resolved,
            lambda correlation_id: bridge_engine.command_abandoned(correlation_id, now),
        )
        confirmed_count = orchestrator.in_flight_commands.confirm_position_report(latest_positions_snapshot_at)
        logger.info(
            "in_flight_registry_reconciled",
            extra={
                "in_flight_count": orchestrator.in_flight_commands.in_flight_count(),
                "resolved_or_expired_this_cycle": resolved_count,
                "awaiting_position_confirmation_count": orchestrator.in_flight_commands.awaiting_position_confirmation_count(),
                "confirmed_this_cycle": confirmed_count,
            },
        )

        for pair in profile.allowed_pairs:
            if news_engine is not None and not news_trusted:
                skipped[pair] = "market_intelligence_not_ready"
                continue
            if account_state is None:
                skipped[pair] = "no_account_state_reported_yet"
                continue
            if not positions_are_live:
                skipped[pair] = "no_recent_position_report"
                continue
            if not market_data_engine.is_ready(pair, _PRIMARY_TIMEFRAME, now):
                skipped[pair] = "market_data_not_ready"
                continue
            spread = market_data_engine.latest_spread(pair)
            if spread is None:
                skipped[pair] = "no_spread_data_yet"
                continue
            current_spread, average_spread = spread
            bars = market_data_engine.get_bars(pair, _PRIMARY_TIMEFRAME)
            inputs[pair] = (
                bars, news_events, current_spread, average_spread, MarketSafetyInputs(),
                PortfolioState(open_positions=open_positions), None, account_state,
            )

        # Run Status diagnostics (item 10): seed the per-pair view from
        # this tick's pre-engine skip reasons, then overwrite with
        # run_cycle()'s own per-pair RuntimeAuditRecord for every pair
        # that actually reached the engines -- previously this record was
        # computed every cycle and immediately discarded (the call below
        # was `orchestrator.run_cycle(...)` with no assignment).
        pair_status: Dict[str, dict] = {
            pair: {"outcome": reason, "reason": reason, "correlation_id": None, "compliance_decision": None}
            for pair, reason in skipped.items()
        }
        last_submitted_correlation_id: Optional[str] = None
        if inputs:
            try:
                cycle_report = orchestrator.run_cycle(tuple(inputs.keys()), profile, inputs, now, cycle_id)
                for record in cycle_report.records:
                    pair_status[record.pair] = {
                        "outcome": record.outcome.value,
                        "reason": record.reasons[0] if record.reasons else None,
                        "correlation_id": record.bridge_correlation_id,
                        "compliance_decision": record.compliance_decision.value if record.compliance_decision is not None else None,
                    }
                    if record.outcome is CycleOutcome.SUBMITTED and record.bridge_correlation_id is not None:
                        last_submitted_correlation_id = record.bridge_correlation_id
            except Exception:  # noqa: BLE001 -- the live-cycle loop must never crash the process
                logger.exception("live cycle %s failed", cycle_id)

        _live_cycle_status.update(now, cycle_id, inputs.keys(), skipped)
        _live_cycle_status.update_decisions(compliance_lock_active, compliance_lock_reason, pair_status, last_submitted_correlation_id)
        _shutdown_event.wait(_LIVE_CYCLE_INTERVAL_SECONDS)


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
    try:
        profile = build_trading_profile(settings)
    except ConfigError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    validation_result = validate_profile(profile, strategy_config, settings.compliance_config)
    if not validation_result.valid:
        logger.error("Trading profile %s failed validation: %s", profile.profile_id, validation_result.issues)
        print(f"FAILED: trading profile validation failed: {validation_result.issues}", file=sys.stderr)
        return 2
    logger.info("Trading profile %s validated OK", profile.profile_id)

    # Amendment 1 (ADR-023): reuses BridgeConfig's own allowed_symbols as
    # the single source of truth for which symbols this deployment
    # ingests market data for -- no second, duplicate pairs list.
    market_data_config = (
        MarketDataIngestionConfig(enabled_pairs=settings.bridge_config.allowed_symbols)
        if settings.bridge_config.allowed_symbols else MarketDataIngestionConfig()
    )
    market_data_metrics = MarketDataIngestionMetrics()
    market_data_engine = MarketDataIngestionEngine(market_data_config, market_data_metrics)

    # Phase 3E (ADR-033 Part 2): Trading Economics primary, Forex
    # Factory backup -- both built from the same NewsProviderSettings
    # config_loader.py already parses. Market Intelligence Engine never
    # knows which provider is active; it only ever sees the events tuple
    # and (indirectly, via the live-cycle loop skipping every pair when
    # untrusted) the fail-closed effect of both providers being down.
    news_ingestion_config = NewsIngestionConfig(
        trading_economics_api_key_env_var=settings.news_provider_settings.trading_economics_api_key_env_var,
        forex_factory_api_key_env_var=settings.news_provider_settings.forex_factory_api_key_env_var,
        trading_economics_base_url=settings.news_provider_settings.trading_economics_base_url,
        forex_factory_base_url=settings.news_provider_settings.forex_factory_base_url,
        request_timeout_seconds=settings.news_provider_settings.request_timeout_seconds,
        max_retries=settings.news_provider_settings.max_retries,
        retry_backoff_seconds=settings.news_provider_settings.retry_backoff_seconds,
        stale_after_seconds=settings.news_provider_settings.stale_after_seconds,
        recovery_health_check_count=settings.news_provider_settings.recovery_health_check_count,
        cache_max_entries=settings.news_provider_settings.cache_max_entries,
    )
    news_ingestion_metrics = NewsIngestionMetrics()
    news_engine = NewsIngestionEngine(
        news_ingestion_config,
        TradingEconomicsProvider(news_ingestion_config),
        ForexFactoryProvider(news_ingestion_config),
        news_ingestion_metrics,
    )

    command_queue = CommandQueue(settings.bridge_config)
    connection_health = ConnectionHealth(settings.bridge_config, _utc_now)
    bridge_metrics = BridgeMetrics()
    bridge_engine = BridgeEngine(
        settings.bridge_config, command_queue, connection_health, _utc_now,
        metrics=bridge_metrics, market_data_engine=market_data_engine,
    )
    # ADR-034: exactly one transport is ever active, selected by
    # bridge.transport ("http" default -- Amendment 4 -- "socket" the
    # native ADR-034 substrate, a fully-supported explicit opt-in).
    # Flip the config field and restart to switch; never a second
    # concurrently-running listener.
    transport_is_socket = settings.bridge_config.transport == "socket"
    active_bridge_port = settings.bridge_config.socket_port if transport_is_socket else settings.bridge_port
    transport_label = "socket" if transport_is_socket else "HTTP"
    try:
        if transport_is_socket:
            transport_server = bridge_serve_socket(
                bridge_engine, settings.bridge_config, _utc_now,
                host=settings.bridge_host, port=active_bridge_port, metrics=bridge_metrics,
            )
        else:
            transport_server = bridge_serve(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=active_bridge_port)
    except OSError as exc:
        logger.error("Bridge %s server failed to bind %s:%s -- %s", transport_label, settings.bridge_host, active_bridge_port, exc)
        print(f"FAILED: Bridge could not bind {settings.bridge_host}:{active_bridge_port}: {exc}", file=sys.stderr)
        return 2
    server_thread = threading.Thread(target=transport_server.serve_forever, name="titan_protocol-bridge-transport", daemon=True)
    server_thread.start()
    logger.info("Bridge %s service listening on %s:%s", transport_label, settings.bridge_host, active_bridge_port)

    # ADR-034 Amendment 3: when socket is the primary transport, also bind
    # an HTTP fallback listener on the same BridgeEngine -- an EA that
    # cannot reach the socket port (e.g. a Tools>Options>Expert Advisors
    # permission this deployment layer cannot pre-validate) falls back to
    # HTTP on its own; without this listener that fallback would just
    # trade one connection failure for another. Bind failure here is a
    # warning, not fatal -- the primary (socket) transport above is
    # already confirmed bound.
    http_fallback_active = False
    fallback_server = None
    if transport_is_socket:
        try:
            fallback_server = bridge_serve(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=settings.bridge_port)
        except OSError as exc:
            logger.warning(
                "Bridge HTTP fallback listener failed to bind %s:%s -- %s (socket transport still "
                "active; an EA that falls back to HTTP will not be reachable until this is resolved)",
                settings.bridge_host, settings.bridge_port, exc,
            )
        else:
            fallback_thread = threading.Thread(target=fallback_server.serve_forever, name="titan_protocol-bridge-http-fallback", daemon=True)
            fallback_thread.start()
            http_fallback_active = True
            logger.info("Bridge HTTP fallback listener also active on %s:%s", settings.bridge_host, settings.bridge_port)

    evidence_engine = EvidenceEngine(EvidenceEngineConfig())
    market_intelligence_engine = MarketIntelligenceEngine(settings.news_config)
    strategy_engine = StrategyEngine(strategy_config)
    risk_engine = RiskEngine(settings.risk_config)
    compliance_engine = ComplianceEngine(settings.compliance_config)
    # Run Status diagnostics (item 10): the position-limit invariant an
    # operator needs alongside "how many positions are actually open" --
    # resolved once here rather than re-looked-up on every health snapshot.
    _selected_compliance_profile = settings.compliance_config.profile_for(settings.compliance_rule_profile_name)
    configured_max_positions_per_pair = _selected_compliance_profile.max_positions_per_pair
    configured_max_account_state_age_seconds = _selected_compliance_profile.max_account_state_age_seconds
    compliance_state_store = ComplianceStateStore(
        ComplianceStateStoreConfig(
            state_file=settings.state_dir / "compliance_state.json",
            daily_reset_hour_utc=settings.compliance_daily_reset_hour_utc,
        )
    )

    def bridge_submit(command, now):
        return bridge_engine.submit_command(command, now)

    runtime_metrics = RuntimeMetrics()
    in_flight_commands = InFlightCommandRegistry(ttl_seconds=_IN_FLIGHT_COMMAND_TTL_SECONDS)
    orchestrator = RuntimeOrchestrator(
        settings.runtime_config, evidence_engine, market_intelligence_engine,
        strategy_engine, risk_engine, compliance_engine, bridge_submit,
        metrics=runtime_metrics, timeframe=_PRIMARY_TIMEFRAME.name,
        in_flight_commands=in_flight_commands,
    )
    logger.info("RuntimeOrchestrator constructed")

    reliability = ReliabilityEngine(settings.reliability_config)
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(reliability, bridge_engine, command_queue, settings.state_dir, settings.bridge_host, active_bridge_port,
              market_data_engine, market_data_metrics, runtime_metrics, news_engine, news_ingestion_metrics),
        kwargs={
            "bridge_transport": settings.bridge_config.transport, "bridge_metrics": bridge_metrics,
            "connection_health": connection_health, "in_flight_commands": in_flight_commands,
            "http_fallback_active": http_fallback_active,
            "configured_max_positions_per_pair": configured_max_positions_per_pair,
            "configured_max_account_state_age_seconds": configured_max_account_state_age_seconds,
        },
        name="titan_protocol-reliability-heartbeat", daemon=True,
    )
    heartbeat_thread.start()

    # Amendment 1 (ADR-023) + Phase 3E (ADR-033 Part 2): the live-cycle
    # loop -- fail-closed per pair via MarketDataIngestionEngine.is_ready(),
    # and fail-closed for every pair at once when both news providers are
    # down, never bypassed.
    live_cycle_thread = threading.Thread(
        target=_live_cycle_loop,
        args=(orchestrator, market_data_engine, bridge_engine, profile, compliance_state_store, news_engine),
        name="titan_protocol-live-cycle", daemon=True,
    )
    live_cycle_thread.start()
    logger.info("Live-cycle loop started (fail-closed per pair on market-data readiness)")

    def _handle_shutdown(signum, _frame):
        logger.info("Received signal %s -- shutting down", signum)
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    print("=" * 72)
    print("TITAN_PROTOCOL DEPLOYMENT LAYER -- STATUS: DEGRADED")
    print(f"  Bridge {transport_label} service : LIVE on {settings.bridge_host}:{active_bridge_port}")
    if transport_is_socket:
        print(f"  Bridge HTTP fallback : {'LIVE on ' + settings.bridge_host + ':' + str(settings.bridge_port) if http_fallback_active else 'NOT ACTIVE (see log -- bind failed)'}")
    print(f"  Trading profile      : {profile.profile_id} (validated OK)")
    print("  5 core engines       : constructed OK")
    print("  Reliability monitor  : running (process-liveness + Bridge/MT5 heartbeats)")
    print("  LIVE TRADING CYCLE   : RUNNING (Amendment 1) -- fails closed per pair")
    print("                          until the EA reports account state and its")
    print("                          bar feed clears warmup/freshness checks.")
    print("  NEWS PROVIDER FAILOVER: RUNNING (Phase 3E) -- Trading Economics")
    print("                          primary, Forex Factory backup; fails closed")
    print("                          for every pair if both are down. No")
    print("                          persisted day-start/peak/lock tracking")
    print("                          yet -- still DEGRADED, never HEALTHY.")
    print("                          See KNOWN_GAPS.md.")
    print("=" * 72)
    logger.warning("STATUS=DEGRADED -- Bridge+Reliability+live-cycle-loop running; see KNOWN_GAPS.md for remaining gaps")

    try:
        while not _shutdown_event.is_set():
            time.sleep(1.0)
    finally:
        logger.info("Stopping Bridge %s server", transport_label)
        transport_server.shutdown()
        transport_server.server_close()
        if fallback_server is not None:
            logger.info("Stopping Bridge HTTP fallback server")
            fallback_server.shutdown()
            fallback_server.server_close()
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
    if is_process_alive(pid):
        return pid
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

    # Runtime Audit Phase 3 -- the foreground process's own stdout (every
    # print()-based line server.py's _log_bridge_lifecycle produces,
    # including the exact rejection-reason evidence) was previously
    # discarded outright: inherited into a new, unwatched console window
    # on Windows (stdout=None + CREATE_NEW_CONSOLE), or sent to os.devnull
    # on POSIX. Neither path left anything to inspect after the fact, which
    # defeats the entire point of that evidence existing. Redirect to a
    # persisted, append-mode file inside log_dir instead -- this changes
    # only where the existing print() output is captured, nothing about
    # what the Bridge accepts, rejects, or does.
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    console_log_path = settings.log_dir / "bridge_console.log"
    console_log = open(console_log_path, "a", encoding="utf-8")
    try:
        subprocess.Popen(
            [python_exe, str(_HERE / "start.py"), "--foreground", "--config", str(config_path)],
            cwd=str(_HERE), creationflags=creation_flags,
            stdout=console_log, stderr=console_log,
            start_new_session=(os.name != "nt"),
        )
    finally:
        console_log.close()  # the child received its own duplicated handle
    print(f"Bridge/runtime console output is captured to {console_log_path}")

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
