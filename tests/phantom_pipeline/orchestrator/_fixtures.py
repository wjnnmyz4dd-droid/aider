"""Shared test-only fixtures for the Pipeline Orchestrator integration
tests. Every value here mirrors an already-proven-working configuration
from each stage's own test suite (e.g. `tests/phantom_pipeline/analytics/
_fixtures.py`'s `make_full_open_chain`, `tests/phantom_pipeline/scanner/
test_scanner.py`'s 120-bar NOMINAL pattern) — nothing here is a novel,
unvetted setup.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from phantom_pipeline.analytics.engine import AnalyticsEngine
from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.engine import ComplianceEngine
from phantom_pipeline.compliance_engine.models import AccountState as ComplianceAccountState
from phantom_pipeline.compliance_engine.models import NewsCalendarState
from phantom_pipeline.compliance_engine.state_store import InMemoryComplianceStateStore
from phantom_pipeline.dashboard.engine import DashboardEngine
from phantom_pipeline.dashboard.prometheus_port import FakePrometheusReadPort
from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.models import DataQuality, MarketSnapshot, NormalizedBar
from phantom_pipeline.data_pipeline.models import SCHEMA_VERSION as PIPELINE_SCHEMA_VERSION
from phantom_pipeline.data_pipeline.pipeline import DataPipeline
from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig
from phantom_pipeline.execution_validator.engine import ExecutionValidator
from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore
from phantom_pipeline.execution_validator.models import AccountState as ExecutionAccountState
from phantom_pipeline.execution_validator.models import BrokerState
from phantom_pipeline.mt5_bridge.broker_adapter import FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.engine import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from phantom_pipeline.orchestrator import PipelineOrchestrator
from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.engine import PositionManager
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from phantom_pipeline.risk_engine.config import RiskEngineConfig
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.risk_engine.models import AccountState as RiskAccountState
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import DataQualityFlag, Direction
from phantom_pipeline.scanner.scanner import Scanner
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from phantom_pipeline.strategy_engine.config import StrategyEngineConfig
from phantom_pipeline.strategy_engine.engine import StrategyEngine
from phantom_pipeline.strategy_engine.models import CandidateTrade, Evidence, SupportingObservation, make_candidate_id
from phantom_pipeline.strategy_engine.playbook import Playbook, PlaybookMetadata
from phantom_pipeline.strategy_engine.registry import StrategyRegistry
from phantom_pipeline.watchdog.engine import WatchdogEngine
from phantom_pipeline.watchdog.recovery_executor import FakeRecoveryActionExecutor
from phantom_pipeline.watchdog.state_store import InMemoryWatchdogStateStore

SYMBOL = "EURUSD"
TIMEFRAME = "M1"
PRIMARY_TIMEFRAME = "M1"
T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)
PRICE = 1.1000
STOP_DISTANCE = 0.0050


class AlwaysFiresPlaybook(Playbook):
    """Test-only deterministic playbook — every real playbook in
    `phantom_pipeline/strategy_engine/playbooks/` is a reserved,
    always-abstains placeholder (`ADR-003` §8), so exercising the full
    Scoring->Risk->Compliance->Execution->MT5 chain requires a
    deterministic hypothesis generator. `StrategyRegistry`'s own
    `playbook_classes` parameter is documented as existing exactly for
    this — "used only by tests ... without touching the real
    playbooks/ package" — so this is the sanctioned mechanism, not a
    workaround."""

    _METADATA = PlaybookMetadata(
        strategy_id="ALWAYS_FIRES",
        version="1.0.0",
        description="Test-only playbook that always proposes one candidate for a NOMINAL observation.",
        supported_symbols=(SYMBOL,),
        supported_timeframes=(TIMEFRAME,),
        schema_versions_supported=(1,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(self, observation, config) -> Tuple[CandidateTrade, ...]:
        if observation.data_quality_flag != DataQualityFlag.NOMINAL:
            return ()
        candidate_id = make_candidate_id(observation.trace_id, self._METADATA.strategy_id, self._METADATA.version)
        return (
            CandidateTrade(
                schema_version=1,
                trace_id=observation.trace_id,
                candidate_id=candidate_id,
                strategy_id=self._METADATA.strategy_id,
                strategy_version=self._METADATA.version,
                symbol=observation.symbol,
                timeframe=TIMEFRAME,
                timestamp=observation.timestamp,
                direction=Direction.UP,
                entry_concept="integration test entry",
                supporting_observations=(SupportingObservation("trend", "up"),),
                evidence=(Evidence("test", "fixture"),),
                reason_codes=("TEST_REASON",),
                reasoning="always-fires test playbook",
            ),
        )


def make_bar(i: int, close: float, timestamp: datetime, timeframe: str = TIMEFRAME, symbol: str = SYMBOL) -> NormalizedBar:
    return NormalizedBar(
        schema_version=PIPELINE_SCHEMA_VERSION,
        trace_id=f"bar-{i}",
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        open=close,
        high=close + 0.0007,
        low=close - 0.0007,
        close=close,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


def feed_healthy_bars(data_pipeline: DataPipeline, count: int = 120, symbol: str = SYMBOL, start: datetime = T0) -> datetime:
    """Ingests `count` M1 ticks (one per minute) through Data Pipeline's
    real ingestion path so Scanner sees NOMINAL-quality, non-warm-up bars
    (the same 120-bar pattern `tests/phantom_pipeline/scanner/
    test_scanner.py` already proves produces a NOMINAL observation).
    Returns the timestamp of the last tick."""
    last_timestamp = start
    for i in range(count):
        price = 1.1000 + (i % 24) * 0.0003
        last_timestamp = start + timedelta(minutes=i)
        data_pipeline.process_raw_tick(
            raw_symbol=symbol,
            raw_timestamp=last_timestamp,
            bid=price,
            ask=price + 0.0002,
            last=None,
            volume=1.0,
            source="test",
            market_status="OPEN",
        )
    data_pipeline.flush(symbol)
    return last_timestamp


def make_risk_account_state(equity: float = 10000.0) -> RiskAccountState:
    return RiskAccountState(
        equity=equity, daily_drawdown_pct=0.0, total_drawdown_pct=0.0,
        consecutive_losses=0, daily_risk_allocated_pct=0.0, open_positions=(),
    )


def make_compliance_account_state(approve: bool = True) -> ComplianceAccountState:
    if approve:
        return ComplianceAccountState(equity=10000.0, balance=10000.0, daily_drawdown_pct=0.5, total_drawdown_pct=0.5, open_positions=())
    return ComplianceAccountState(equity=10000.0, balance=10000.0, daily_drawdown_pct=9.0, total_drawdown_pct=9.0, open_positions=())


def make_execution_account_state() -> ExecutionAccountState:
    return ExecutionAccountState(equity=10000.0, available_margin=5000.0)


def make_broker_state(connected: bool = True, tradable: Optional[bool] = True) -> BrokerState:
    return BrokerState(connected=connected, symbol_tradable=tradable)


def make_news_state(stale: bool = False) -> NewsCalendarState:
    return NewsCalendarState(feed_stale=stale, blackout_windows=())


def make_market_snapshot(symbol: str = SYMBOL, price: float = PRICE, timestamp: datetime = T0) -> MarketSnapshot:
    return MarketSnapshot(
        schema_version=PIPELINE_SCHEMA_VERSION, trace_id="snap", symbol=symbol,
        timestamp=timestamp, price=price, spread=0.0002, market_status="OPEN",
    )


def build_orchestrator(broker_connect_result: bool = True) -> PipelineOrchestrator:
    """Wires all 12 stage engines together with fresh Fake adapters/
    in-memory stores — a fresh call produces a fully independent
    orchestrator instance (no shared state across calls), used by the
    "pipeline restart" test to prove independence."""
    data_pipeline = DataPipeline(PipelineConfig())
    scanner = Scanner(ScannerConfig())
    strategy_registry = StrategyRegistry(playbook_classes=[AlwaysFiresPlaybook])
    strategy_engine = StrategyEngine(strategy_registry, StrategyEngineConfig(enabled_playbooks={"ALWAYS_FIRES": True}))
    scoring_registry = ScoringRuleRegistry()
    scoring_engine = ScoringEngine(scoring_registry, ScoringEngineConfig(enabled_rules={rid: True for rid in scoring_registry.registered_ids}))
    risk_engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))
    compliance_engine = ComplianceEngine(
        InMemoryComplianceStateStore(),
        ComplianceEngineConfig(spread_thresholds={SYMBOL: 0.0005}, slippage_thresholds={SYMBOL: 0.0005}),
    )
    execution_validator = ExecutionValidator(
        InMemoryIdempotencyStore(300.0), ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005})
    )
    broker_adapter = FakeBrokerAdapter(connect_result=broker_connect_result)
    mt5_bridge = MT5Bridge(broker_adapter, InMemoryTransportIdempotencyStore(3600.0))
    position_manager = PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig())
    analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
    watchdog = WatchdogEngine(InMemoryWatchdogStateStore(), FakeRecoveryActionExecutor())
    prometheus_port = FakePrometheusReadPort()
    dashboard = DashboardEngine(prometheus_port)

    return PipelineOrchestrator(
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


def run_ready_cycle(orchestrator: PipelineOrchestrator, now: datetime = None, compliance_approve: bool = True):
    """Feeds 120 healthy bars, connects+synchronizes MT5 Bridge to READY,
    then runs one `run_scan_cycle`. Returns (cycle_result, now).

    `reference_price`/`intended_stop_loss`/`intended_take_profit` are
    derived from Data Pipeline's own final `MarketSnapshot` price (never
    a hardcoded constant) — Execution Validator's `SLIPPAGE_WITHIN_LIMITS`
    and `MINIMUM_RR` checks compare the intended levels against the
    *actual* fresh snapshot price, so a fixture using a stale constant
    would fail those checks not because of an orchestrator defect but
    because the fixture's own inputs were internally inconsistent."""
    last_tick_at = feed_healthy_bars(orchestrator.data_pipeline)
    now = now or last_tick_at
    orchestrator.mt5_bridge.connect(now)
    orchestrator.mt5_bridge.synchronize(now, expected_position_ids=())

    entry_price = orchestrator.data_pipeline.get_snapshot(SYMBOL).price

    result = orchestrator.run_scan_cycle(
        symbol=SYMBOL,
        timeframes=(TIMEFRAME,),
        primary_timeframe=PRIMARY_TIMEFRAME,
        session_time=now,
        now=now,
        risk_account_state=make_risk_account_state(),
        compliance_account_state=make_compliance_account_state(approve=compliance_approve),
        execution_account_state=make_execution_account_state(),
        broker_state=make_broker_state(),
        news_state=make_news_state(),
        stop_distance=STOP_DISTANCE,
        expected_slippage=0.0001,
        reference_price=entry_price,
        intended_stop_loss=entry_price - STOP_DISTANCE,
        intended_take_profit=entry_price + STOP_DISTANCE * 3,
    )
    return result, now
