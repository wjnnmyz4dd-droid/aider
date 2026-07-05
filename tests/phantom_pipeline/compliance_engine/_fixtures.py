"""Shared test-only fixtures for the Compliance Engine test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from phantom_pipeline.compliance_engine.models import AccountState, OpenPosition
from phantom_pipeline.data_pipeline.models import MarketSnapshot
from phantom_pipeline.data_pipeline.models import SCHEMA_VERSION as PIPELINE_SCHEMA_VERSION
from phantom_pipeline.risk_engine.config import DEFAULT_CONFIG as RISK_DEFAULT_CONFIG
from phantom_pipeline.risk_engine.engine import RiskEngine
from phantom_pipeline.scanner.models import Direction
from phantom_pipeline.scoring_engine.config import ScoringEngineConfig
from phantom_pipeline.scoring_engine.engine import ScoringEngine
from phantom_pipeline.scoring_engine.registry import ScoringRuleRegistry
from phantom_pipeline.strategy_engine.models import (
    CandidateTrade,
    Evidence,
    SupportingObservation,
    make_candidate_id,
)

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)  # a Monday
SYMBOL = "EURUSD"
TIMEFRAME = "M1"


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


def make_risk_decision(candidate: CandidateTrade, score_result, equity: float = 10000.0):
    from phantom_pipeline.risk_engine.config import RiskEngineConfig
    from phantom_pipeline.risk_engine.models import AccountState as RiskAccountState

    risk_account = RiskAccountState(
        equity=equity,
        daily_drawdown_pct=0.0,
        total_drawdown_pct=0.0,
        consecutive_losses=0,
        daily_risk_allocated_pct=0.0,
        open_positions=(),
    )
    engine = RiskEngine(RiskEngineConfig(correlation_buckets={SYMBOL: "MAJORS"}))
    return engine.decide(score_result, candidate, _fake_observation(), risk_account)


def _fake_observation():
    from dataclasses import dataclass

    from phantom_pipeline.scanner.models import VolatilityLabel, VolatilityState

    @dataclass(frozen=True)
    class _FakeObservation:
        volatility: VolatilityState

    return _FakeObservation(volatility=VolatilityState(label=VolatilityLabel.NORMAL, ratio=1.0))


def make_account_state(
    equity: Optional[float] = 10000.0,
    balance: Optional[float] = 10000.0,
    daily_drawdown_pct: Optional[float] = 0.5,
    total_drawdown_pct: Optional[float] = 0.5,
    open_positions: Tuple[OpenPosition, ...] = (),
) -> AccountState:
    return AccountState(
        equity=equity,
        balance=balance,
        daily_drawdown_pct=daily_drawdown_pct,
        total_drawdown_pct=total_drawdown_pct,
        open_positions=open_positions,
    )


def make_market_snapshot(
    symbol: str = SYMBOL,
    spread: Optional[float] = 0.0001,
    market_status: str = "OPEN",
    timestamp: datetime = T0,
) -> MarketSnapshot:
    return MarketSnapshot(
        schema_version=PIPELINE_SCHEMA_VERSION,
        trace_id="snap",
        symbol=symbol,
        timestamp=timestamp,
        price=1.1,
        spread=spread,
        market_status=market_status,
    )
