"""Shared test-only fixtures for the Risk Engine test suite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from phantom_pipeline.data_pipeline.models import (
    DataQuality,
    MarketSnapshot,
    NormalizedBar,
    SCHEMA_VERSION as PIPELINE_SCHEMA_VERSION,
)
from phantom_pipeline.risk_engine.models import AccountState, OpenPosition
from phantom_pipeline.scanner import Scanner, ScannerConfig
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

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
SYMBOL = "EURUSD"
TIMEFRAME = "M1"


def _bar(i: int, price: float) -> NormalizedBar:
    return NormalizedBar(
        schema_version=PIPELINE_SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        timestamp=T0 + timedelta(minutes=i),
        open=price,
        high=price + 0.001,
        low=price - 0.001,
        close=price,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


def nominal_observation(bar_count: int = 120):
    bars = [_bar(i, 1.1000 + (i % 20) * 0.0002) for i in range(bar_count)]
    snapshot = MarketSnapshot(
        schema_version=PIPELINE_SCHEMA_VERSION,
        trace_id="snap",
        symbol=SYMBOL,
        timestamp=bars[-1].timestamp,
        price=1.1,
        spread=0.0002,
        market_status="OPEN",
    )
    return Scanner(ScannerConfig()).scan(SYMBOL, {TIMEFRAME: bars}, snapshot, bars[-1].timestamp, TIMEFRAME)


@dataclass(frozen=True)
class _FakeVolatility:
    volatility: VolatilityState


def observation_with_volatility(label: VolatilityLabel):
    """A lightweight, duck-typed stand-in exposing only `.volatility.label`
    — sufficient for isolated `constraints.volatility_adjustment` unit
    tests, which read no other field."""
    return _FakeVolatility(volatility=VolatilityState(label=label, ratio=1.0))


def make_candidate(
    strategy_id: str = "TEST_STRATEGY",
    direction: Direction = Direction.UP,
    trace_id: str = "obs-trace-1",
    symbol: str = SYMBOL,
) -> CandidateTrade:
    return CandidateTrade(
        schema_version=1,
        trace_id=trace_id,
        candidate_id=make_candidate_id(trace_id, strategy_id, "1.0.0"),
        strategy_id=strategy_id,
        strategy_version="1.0.0",
        symbol=symbol,
        timeframe=TIMEFRAME,
        timestamp=T0,
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


def make_account_state(
    equity: Optional[float] = 10000.0,
    daily_drawdown_pct: Optional[float] = 1.0,
    total_drawdown_pct: Optional[float] = 1.0,
    consecutive_losses: Optional[int] = 0,
    daily_risk_allocated_pct: Optional[float] = 0.0,
    open_positions: Tuple[OpenPosition, ...] = (),
) -> AccountState:
    return AccountState(
        equity=equity,
        daily_drawdown_pct=daily_drawdown_pct,
        total_drawdown_pct=total_drawdown_pct,
        consecutive_losses=consecutive_losses,
        daily_risk_allocated_pct=daily_risk_allocated_pct,
        open_positions=open_positions,
    )
