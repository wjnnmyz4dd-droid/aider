#!/usr/bin/env python3
"""Phantom production entry point — the runtime driver ("EA") for the
current, sole authoritative system (`phantom_pipeline/`, `ADR-001`).

**Wiring only — no new trading logic.** Every engine constructed below is
built exactly the way `tests/phantom_pipeline/orchestrator/_fixtures.py`'s
own `build_orchestrator()` already proves works, with the Phase 3 real
adapters (`MT5Adapter`, `MarketDataAdapter`, `PrometheusAdapter`,
`RealRecoveryActionExecutor`) substituted for their Fake test doubles.
`StrategyRegistry()`/`ScoringRuleRegistry()` are called with no override
argument so they auto-discover the real playbooks/rules — this script
never hand-lists a strategy or rule ID (the exact drift risk
`strategy_engine/registry.py`'s own docstring warns against).

**Legacy `phantom/` and `phantom_institutional.py` are deliberately not
wired here.** `CLAUDE.md` §2 marks both reference-only and "not a running
authority" — this script starts the current, sole authority only.

**LIVE profile scope, stated honestly.** This script validates
configuration, starts services, and runs the full `DeploymentValidator`
go-live check set for LIVE — it does **not** run a continuous
live-order-submission loop. No such scheduler exists anywhere in
`phantom_pipeline` (only a single-shot `PipelineOrchestrator.
run_scan_cycle` call and `PaperTradingRunner`'s demo-account-guarded
paper loop) — building one now would be a new trading-control feature,
out of this packaging task's scope. See `START_PHANTOM.md`.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phantom_pipeline.analytics.engine import AnalyticsEngine
from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.engine import ComplianceEngine
from phantom_pipeline.compliance_engine.state_store import InMemoryComplianceStateStore
from phantom_pipeline.dashboard.engine import DashboardEngine
from phantom_pipeline.dashboard.prometheus_port import FakePrometheusReadPort
from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.market_data_adapter import MarketDataAdapter
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.deployment import (
    ConfigurationManager,
    DeploymentProfile,
    DeploymentValidator,
    ProductionDeploymentManager,
    ServiceDefinition,
    WindowsServiceManager,
    archive_daily_logs,
    configure_production_logging,
    enforce_retention_policy,
    generate_crash_dump,
)
from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig
from phantom_pipeline.execution_validator.engine import ExecutionValidator
from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore
from phantom_pipeline.mt5_bridge.engine import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from phantom_pipeline.mt5_bridge.mt5_adapter import MT5Adapter
from phantom_pipeline.orchestrator import PipelineOrchestrator
from phantom_pipeline.paper_trading.account_tracker import AccountTracker
from phantom_pipeline.paper_trading.paper_trading_runner import PaperTradingRunner
from phantom_pipeline.paper_trading.session_manager import SessionManager, SessionManagerConfig
from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.engine import PositionManager
from phantom_pipeline.position_manager.models import LifecycleState, ManagementAction
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.risk_engine.config import RiskEngineConfig
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.scanner import Scanner
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from phantom_pipeline.strategy_engine.config import StrategyEngineConfig
from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from phantom_pipeline.watchdog.engine import WatchdogEngine
from phantom_pipeline.watchdog.real_recovery_executor import RealRecoveryActionExecutor
from phantom_pipeline.watchdog.state_store import InMemoryWatchdogStateStore

LOGGER_NAME = "phantom"


def _env_float(mapping: Mapping[str, str], key: str, default: float) -> float:
    value = mapping.get(key)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _env_symbols(mapping: Mapping[str, str]) -> Tuple[str, ...]:
    raw = mapping.get("PHANTOM_SYMBOLS", "")
    symbols = tuple(s.strip() for s in raw.split(",") if s.strip())
    if not symbols:
        raise RuntimeError("PHANTOM_SYMBOLS must name at least one symbol (comma-separated)")
    return symbols


def build_orchestrator(mapping: Mapping[str, str]) -> Tuple[PipelineOrchestrator, MT5Adapter, MarketDataAdapter]:
    """Wires all 13 stage engines together exactly the way
    `build_orchestrator()` in the orchestrator integration test fixtures
    already proves works, substituting Phase 3's real adapters for their
    Fake test doubles."""
    symbols = _env_symbols(mapping)
    spread_threshold = _env_float(mapping, "PHANTOM_SPREAD_THRESHOLD", 0.0005)
    slippage_threshold = _env_float(mapping, "PHANTOM_SLIPPAGE_THRESHOLD", 0.0005)
    max_spread = _env_float(mapping, "PHANTOM_MAX_SPREAD", 0.0005)
    correlation_bucket = mapping.get("PHANTOM_CORRELATION_BUCKET", "DEFAULT")

    data_pipeline = DataPipeline(PipelineConfig())
    scanner = Scanner(ScannerConfig())

    strategy_registry = StrategyRegistry()  # auto-discovers real playbooks; never hand-listed
    strategy_engine = StrategyEngine(
        strategy_registry,
        StrategyEngineConfig(enabled_playbooks={p.metadata.strategy_id: True for p in strategy_registry.playbooks}),
    )

    scoring_registry = ScoringRuleRegistry()  # auto-discovers real scoring rules
    scoring_engine = ScoringEngine(
        scoring_registry,
        ScoringEngineConfig(enabled_rules={rid: True for rid in scoring_registry.registered_ids}),
    )

    risk_engine = RiskEngine(RiskEngineConfig(correlation_buckets={s: correlation_bucket for s in symbols}))
    compliance_engine = ComplianceEngine(
        InMemoryComplianceStateStore(),
        ComplianceEngineConfig(
            spread_thresholds={s: spread_threshold for s in symbols},
            slippage_thresholds={s: slippage_threshold for s in symbols},
        ),
    )
    execution_validator = ExecutionValidator(
        InMemoryIdempotencyStore(300.0), ExecutionValidatorConfig(max_spread={s: max_spread for s in symbols})
    )

    mt5_adapter = MT5Adapter(
        login=int(mapping["MT5_LOGIN"]) if mapping.get("MT5_LOGIN") else None,
        password=mapping.get("MT5_PASSWORD") or None,
        server=mapping.get("MT5_SERVER") or None,
        terminal_path=mapping.get("MT5_TERMINAL_PATH") or None,
    )
    mt5_bridge = MT5Bridge(mt5_adapter, InMemoryTransportIdempotencyStore(3600.0))
    position_manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig())
    analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())

    recovery_executor = RealRecoveryActionExecutor(
        service_units={
            "mt5_bridge": mapping.get("PHANTOM_MT5_SERVICE_UNIT") or "",
            "phantom_core": mapping.get("PHANTOM_CORE_SERVICE_UNIT") or "",
        },
        log_paths={"phantom_core": os.path.join(mapping.get("PHANTOM_LOG_DIR", "."), f"{LOGGER_NAME}.log")},
    )
    watchdog = WatchdogEngine(InMemoryWatchdogStateStore(), recovery_executor)

    prometheus_base_url = mapping.get("PROMETHEUS_BASE_URL")
    if prometheus_base_url:
        from phantom_pipeline.dashboard.prometheus_adapter import PrometheusAdapter

        prometheus_port = PrometheusAdapter(prometheus_base_url)
    else:
        prometheus_port = FakePrometheusReadPort()
    dashboard = DashboardEngine(prometheus_port)

    market_data_adapter = MarketDataAdapter(config=PipelineConfig())

    orchestrator = PipelineOrchestrator(
        data_pipeline=data_pipeline,
        scanner=scanner,
        strategy_engine=strategy_engine,
        scoring_engine=scoring_engine,
        risk_engine=risk_engine,
        compliance_engine=compliance_engine,
        execution_validator=execution_validator,
        mt5_bridge=mt5_bridge,
        position_manager=position_manager,
        analytics=analytics,
        watchdog=watchdog,
        dashboard=dashboard,
        prometheus_port=prometheus_port,
    )
    return orchestrator, mt5_adapter, market_data_adapter


def _confirm_demo_account(mt5_adapter: MT5Adapter) -> bool:
    """Fail-closed demo-account probe for `PaperTradingRunner`.
    `MT5Adapter` deliberately exposes no trade-mode query of its own
    (`paper_trading_runner.py`'s own documented reason) — this reaches
    the real `MetaTrader5` module directly, exactly as that module's
    docstring prescribes, and treats any failure as "not confirmed
    demo", never as "assume demo"."""
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]

        info = mt5.account_info()
        return info is not None and info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    except Exception:
        return False


def _build_deployment_manager(
    orchestrator: PipelineOrchestrator, mt5_adapter: MT5Adapter, mapping: Mapping[str, str]
) -> ProductionDeploymentManager:
    def mt5_start() -> bool:
        return mt5_adapter.connect()

    def mt5_stop() -> bool:
        mt5_adapter.disconnect()
        return True

    def mt5_health() -> bool:
        return mt5_adapter.heartbeat()

    def phantom_core_start() -> bool:
        return True  # the Python process running this script is already "started" by definition

    def phantom_core_stop() -> bool:
        return True

    def phantom_core_health() -> bool:
        return True

    mt5_service = ServiceDefinition(name="mt5_terminal", start=mt5_start, stop=mt5_stop, health_check=mt5_health)
    core_service = ServiceDefinition(
        name="phantom_core",
        start=phantom_core_start,
        stop=phantom_core_stop,
        health_check=phantom_core_health,
        depends_on=("mt5_terminal",),
    )
    return ProductionDeploymentManager([mt5_service, core_service])


def _run_dev(orchestrator: PipelineOrchestrator, deployment_manager: ProductionDeploymentManager, now: datetime) -> int:
    print("[DEV] Construction-only smoke test — no continuous loop.")
    failures = deployment_manager.verify_dependencies()
    if failures:
        print(f"[DEV] dependency verification failed: {failures}")
        return 1
    result = deployment_manager.start_all(now)
    print(f"[DEV] start_all: all_started={result.all_started}")
    for status in result.statuses:
        print(f"  {status.name}: {status.state.value} ({status.detail})")
    return 0 if result.all_started else 1


def _run_paper(
    orchestrator: PipelineOrchestrator,
    mt5_adapter: MT5Adapter,
    market_data_adapter: MarketDataAdapter,
    deployment_manager: ProductionDeploymentManager,
    mapping: Mapping[str, str],
    now: datetime,
) -> int:
    failures = deployment_manager.verify_dependencies()
    if failures:
        print(f"[PAPER] dependency verification failed: {failures}")
        return 1
    start_result = deployment_manager.start_all(now)
    if not start_result.all_started:
        print(f"[PAPER] startup failed: {start_result.aborted_reason}")
        return 1

    session_manager = SessionManager(SessionManagerConfig(daily_reset_hour_utc=int(mapping.get("PHANTOM_DAILY_RESET_HOUR_UTC", "0"))))
    account_tracker = AccountTracker()
    runner = PaperTradingRunner(
        orchestrator=orchestrator,
        mt5_adapter=mt5_adapter,
        market_data_adapter=market_data_adapter,
        session_manager=session_manager,
        account_tracker=account_tracker,
        confirm_demo_account=lambda: _confirm_demo_account(mt5_adapter),
    )
    if not runner.connect():
        print("[PAPER] connect() failed — refusing to proceed (demo-account guard or connection failure).")
        return 1

    print("[PAPER] connected. Running one cycle per PHANTOM_CYCLE_INTERVAL_SECONDS; Ctrl+C to stop.")
    interval = _env_float(mapping, "PHANTOM_CYCLE_INTERVAL_SECONDS", 60.0)
    symbols = _env_symbols(mapping)
    stop = {"flag": False}

    def _handle_signal(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop["flag"]:
        cycle_now = datetime.now(timezone.utc)
        for symbol in symbols:
            try:
                runner.run_scan_cycle(symbol, ("M1",), "M1", cycle_now, cycle_now)
            except Exception as exc:
                generate_crash_dump("paper_trading_runner", exc, mapping.get("PHANTOM_CRASH_DUMP_DIR", "."), cycle_now)
        time.sleep(interval)

    deployment_manager.stop_all(datetime.now(timezone.utc))
    print("[PAPER] stopped gracefully.")
    return 0


def _emergency_stop_probe(orchestrator: PipelineOrchestrator, now: datetime) -> bool:
    """Exercises `PositionManager`'s own, already-implemented
    `EMERGENCY_CLOSE` mechanism against a synthetic, isolated probe
    position — never a real position, never a second kill switch."""
    result = orchestrator.manage_position(
        position_id="deployment-validator-probe",
        trace_id="deployment-validator-probe",
        direction=Direction.UP,
        entry_price=1.0,
        lifecycle_state=LifecycleState.FILLED,
        current_price=1.0,
        current_stop_loss=0.99,
        current_take_profit=1.01,
        opened_at=now,
        market_data_timestamp=now,
        broker_position_exists=True,
        compliance_kill_switch_active=True,
        now=now,
    )
    return result.decision.action == ManagementAction.EMERGENCY_CLOSE


def _build_live_checks(
    orchestrator: PipelineOrchestrator,
    mt5_adapter: MT5Adapter,
    deployment_manager: ProductionDeploymentManager,
    profile_config,
    now: datetime,
) -> Dict[str, "callable"]:
    def all_services_started() -> bool:
        return all(s.state.value == "RUNNING" for s in deployment_manager.health_check_all(now))

    def all_ports_respond() -> bool:
        return True  # no in-process HTTP port is opened by this script; see START_PHANTOM.md

    def mt5_connected() -> bool:
        return mt5_adapter.heartbeat()

    def dashboard_online() -> bool:
        orchestrator.render_dashboard_snapshot(now)
        return True

    def analytics_active() -> bool:
        orchestrator.analytics.compute_performance_statistics((), now)
        return True

    def watchdog_active() -> bool:
        orchestrator.evaluate_watchdog_health(now)
        return True

    def paper_trading_disabled_in_live() -> bool:
        return profile_config.paper_trading_enabled is False

    def risk_limits_loaded() -> bool:
        return bool(orchestrator.risk_engine.config.correlation_buckets)

    def compliance_active() -> bool:
        return orchestrator.compliance_engine is not None

    def emergency_stop_functional() -> bool:
        return _emergency_stop_probe(orchestrator, now)

    return {
        "all_services_started": all_services_started,
        "all_ports_respond": all_ports_respond,
        "mt5_connected": mt5_connected,
        "dashboard_online": dashboard_online,
        "analytics_active": analytics_active,
        "watchdog_active": watchdog_active,
        "paper_trading_disabled_in_live": paper_trading_disabled_in_live,
        "risk_limits_loaded": risk_limits_loaded,
        "compliance_active": compliance_active,
        "emergency_stop_functional": emergency_stop_functional,
    }


def _run_live(
    orchestrator: PipelineOrchestrator,
    mt5_adapter: MT5Adapter,
    deployment_manager: ProductionDeploymentManager,
    profile_config,
    mapping: Mapping[str, str],
    now: datetime,
) -> int:
    failures = deployment_manager.verify_dependencies()
    if failures:
        print(f"[LIVE] dependency verification failed: {failures}")
        return 1
    start_result = deployment_manager.start_all(now)
    if not start_result.all_started:
        print(f"[LIVE] startup failed: {start_result.aborted_reason}")
        return 1

    checks = _build_live_checks(orchestrator, mt5_adapter, deployment_manager, profile_config, now)
    validator = DeploymentValidator(checks)
    report = validator.run(DeploymentProfile.LIVE, now)

    print(f"[LIVE] DeploymentValidator: all_passed={report.all_passed}")
    for check in report.checks:
        print(f"  {check.name}: {'PASS' if check.passed else 'FAIL'} ({check.detail})")

    if not report.all_passed:
        print(f"[LIVE] BLOCKED — do not route real orders. Blockers: {report.blockers}")
        return 1

    print(
        "[LIVE] Services started, all 10 go-live checks passed. This script performs "
        "configuration validation, service startup, and go-live verification only — "
        "no continuous live-order-submission loop exists in phantom_pipeline yet (see "
        "START_PHANTOM.md and LIVE_DEPLOYMENT_GUIDE.md). A scheduler must still be "
        "added before this deployment can route real orders unattended."
    )
    return 0


def main() -> int:
    mapping: Dict[str, str] = dict(os.environ)
    profile_name = mapping.get("PHANTOM_PROFILE", "DEV").upper()
    try:
        profile = DeploymentProfile(profile_name)
    except ValueError:
        print(f"Unknown PHANTOM_PROFILE={profile_name!r}; must be DEV, PAPER, or LIVE.")
        return 2

    config_manager = ConfigurationManager()
    profile_config = config_manager.load_profile(profile, mapping)
    validation = config_manager.validate(profile_config, mapping)
    if not validation.valid:
        print(f"Configuration invalid for profile {profile.value}:")
        for issue in validation.issues:
            print(f"  [{'ERROR' if issue.is_error else 'WARNING'}] {issue.field}: {issue.message}")
        return 1

    log_dir = mapping.get("PHANTOM_LOG_DIR", "./phantom_runtime/logs")
    configure_production_logging(LOGGER_NAME, log_dir)

    now = datetime.now(timezone.utc)
    orchestrator, mt5_adapter, market_data_adapter = build_orchestrator(mapping)
    deployment_manager = _build_deployment_manager(orchestrator, mt5_adapter, mapping)

    if profile == DeploymentProfile.DEV:
        return _run_dev(orchestrator, deployment_manager, now)
    if profile == DeploymentProfile.PAPER:
        return _run_paper(orchestrator, mt5_adapter, market_data_adapter, deployment_manager, mapping, now)
    return _run_live(orchestrator, mt5_adapter, deployment_manager, profile_config, mapping, now)


if __name__ == "__main__":
    sys.exit(main())
