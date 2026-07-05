"""Shared test-only fixtures for the Analytics test suite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig
from phantom_pipeline.compliance_engine.engine import ComplianceEngine
from phantom_pipeline.compliance_engine.models import AccountState as ComplianceAccountState
from phantom_pipeline.compliance_engine.models import NewsCalendarState
from phantom_pipeline.compliance_engine.state_store import InMemoryComplianceStateStore
from phantom_pipeline.data_pipeline.models import MarketSnapshot
from phantom_pipeline.data_pipeline.models import SCHEMA_VERSION as PIPELINE_SCHEMA_VERSION
from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig
from phantom_pipeline.execution_validator.engine import ExecutionValidator
from phantom_pipeline.execution_validator.idempotency_store import InMemoryIdempotencyStore
from phantom_pipeline.execution_validator.models import AccountState as EVAccountState
from phantom_pipeline.execution_validator.models import BrokerState as EVBrokerState
from phantom_pipeline.mt5_bridge.broker_adapter import FakeBrokerAdapter
from phantom_pipeline.mt5_bridge.engine import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore
from phantom_pipeline.mt5_bridge.models import ExecutionReceipt, FillReport
from phantom_pipeline.position_manager.config import PositionManagerConfig
from phantom_pipeline.position_manager.engine import PositionManager
from phantom_pipeline.position_manager.state_store import InMemoryPositionManagerStateStore
from phantom_pipeline.risk_engine.config import RiskEngineConfig
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.risk_engine.models import AccountState as RiskAccountState
from phantom_pipeline.scanner.models import Direction, VolatilityLabel, VolatilityState
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from phantom_pipeline.strategy_engine.models import (
    CandidateTrade,
    Evidence,
    SupportingObservation,
    make_candidate_id,
)

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD"
TIMEFRAME = "M1"
PRICE = 1.1000
STOP_DISTANCE = 0.0050


def make_candidate(
    strategy_id: str = "TEST_STRATEGY",
    direction: Direction = Direction.UP,
    trace_id: str = "obs-trace-1",
    symbol: str = SYMBOL,
    timestamp: datetime = T0,
) -> CandidateTrade:
    return CandidateTrade(
        schema_version=1,
        trace_id=trace_id,
        candidate_id=make_candidate_id(trace_id, strategy_id, "1.0.0"),
        strategy_id=strategy_id,
        strategy_version="1.0.0",
        symbol=symbol,
        timeframe=TIMEFRAME,
        timestamp=timestamp,
        direction=direction,
        entry_concept="fixture entry zone",
        supporting_observations=(SupportingObservation("trend", "detail"),),
        evidence=(Evidence("key", "value"),),
        reason_codes=("REASON_0",),
        reasoning="fixture reasoning",
    )


def make_score_result(candidate: CandidateTrade):
    registry = ScoringRuleRegistry()
    config = ScoringEngineConfig(enabled_rules={rid: True for rid in registry.registered_ids})
    return ScoringEngine(registry, config).score(candidate)


@dataclass(frozen=True)
class _FakeObservation:
    volatility: VolatilityState


def make_risk_decision(candidate: CandidateTrade, score_result, equity: float = 10000.0):
    risk_account = RiskAccountState(
        equity=equity, daily_drawdown_pct=0.0, total_drawdown_pct=0.0,
        consecutive_losses=0, daily_risk_allocated_pct=0.0, open_positions=(),
    )
    observation = _FakeObservation(volatility=VolatilityState(label=VolatilityLabel.NORMAL, ratio=1.0))
    engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))
    return engine.decide(score_result, candidate, observation, risk_account, stop_distance=STOP_DISTANCE)


def make_market_snapshot(
    symbol: str = SYMBOL, price=PRICE, spread=0.0001, market_status: str = "OPEN", timestamp: datetime = T0
) -> MarketSnapshot:
    return MarketSnapshot(
        schema_version=PIPELINE_SCHEMA_VERSION, trace_id="snap", symbol=symbol, timestamp=timestamp,
        price=price, spread=spread, market_status=market_status,
    )


def make_compliance_decision(candidate, score_result, risk_decision, verdict_approve: bool = True):
    config = ComplianceEngineConfig(spread_thresholds={SYMBOL: 0.0005}, slippage_thresholds={SYMBOL: 0.0005})
    engine = ComplianceEngine(InMemoryComplianceStateStore(), config)
    if verdict_approve:
        account = ComplianceAccountState(equity=10000.0, balance=10000.0, daily_drawdown_pct=0.5, total_drawdown_pct=0.5, open_positions=())
    else:
        account = ComplianceAccountState(equity=10000.0, balance=10000.0, daily_drawdown_pct=9.0, total_drawdown_pct=9.0, open_positions=())
    snapshot = make_market_snapshot()
    news = NewsCalendarState(feed_stale=False, blackout_windows=())
    return engine.evaluate(risk_decision, candidate, score_result, account, snapshot, news, expected_slippage=0.0001)


def make_execution_decision(candidate, score_result, risk_decision, compliance_decision):
    config = ExecutionValidatorConfig(max_spread={SYMBOL: 0.0005})
    engine = ExecutionValidator(InMemoryIdempotencyStore(300.0), config)
    return engine.validate(
        compliance_decision, risk_decision, score_result, candidate,
        make_market_snapshot(), EVBrokerState(connected=True, symbol_tradable=True),
        EVAccountState(equity=10000.0, available_margin=5000.0), T0,
        reference_price=PRICE, intended_stop_loss=PRICE - STOP_DISTANCE, intended_take_profit=PRICE + STOP_DISTANCE * 2,
    )


def make_broker_ack_and_request(candidate, risk_decision, compliance_decision, execution_decision):
    adapter = FakeBrokerAdapter()
    bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0))
    bridge.connect(T0)
    bridge.synchronize(T0, expected_position_ids=())
    _, broker_request, response = bridge.submit_order(execution_decision, risk_decision, compliance_decision, candidate, T0)
    return broker_request, response


def make_fill_report(broker_request) -> FillReport:
    return FillReport(
        schema_version=1, execution_id=broker_request.execution_id, trace_id=broker_request.trace_id,
        fill_price=PRICE, fill_size=broker_request.lot_size, fill_timestamp=T0,
    )


def make_full_open_chain(trace_id: str = "obs-trace-1", verdict_approve: bool = True):
    candidate = make_candidate(trace_id=trace_id)
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(candidate, score_result)
    compliance_decision = make_compliance_decision(candidate, score_result, risk_decision, verdict_approve)
    if not verdict_approve:
        return candidate, score_result, risk_decision, compliance_decision, None, None, None
    execution_decision = make_execution_decision(candidate, score_result, risk_decision, compliance_decision)
    broker_request, response = make_broker_ack_and_request(candidate, risk_decision, compliance_decision, execution_decision)
    fill_report = make_fill_report(broker_request)
    return candidate, score_result, risk_decision, compliance_decision, execution_decision, response, fill_report


def new_position_manager() -> PositionManager:
    return PositionManager(InMemoryPositionManagerStateStore(), PositionManagerConfig(breakeven_trigger_distance=100.0))
