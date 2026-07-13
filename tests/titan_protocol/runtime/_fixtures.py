"""Shared test-only fixtures for the Runtime Orchestrator test suite --
reuses `risk_engine`'s and `compliance_engine`'s own fixture builders
for `EvidenceSnapshot`/`MarketIntelligenceSnapshot`/`StrategySnapshot`/
`RiskSnapshot`/`ComplianceSnapshot` (no second, divergent construction
of the same upstream types) and adds recording stub engines -- mirrors
`docs/specs/00_runtime_orchestrator.md` SS10's own "recording stubs" test
design, restated for the real six-engine pipeline."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from titan_protocol.compliance_engine.explainability import build_compliance_snapshot
from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.evidence_engine.models import Bar
from titan_protocol.market_intelligence.models import MarketSafetyInputs
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.runtime.config import RuntimeConfig
from titan_protocol.runtime.models import TradingProfile, TradingWindow
from titan_protocol.runtime.profiles import make_custom_profile
from titan_protocol.strategy_engine.models import StrategySnapshot, TradeIntent
from tests.titan_protocol.compliance_engine._fixtures import make_account_state, make_risk_snapshot
from tests.titan_protocol.risk_engine._fixtures import make_evidence_snapshot, make_mi_snapshot, make_strategy_snapshot

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap, hour 13


def make_config(**overrides) -> RuntimeConfig:
    return RuntimeConfig(**overrides)


def make_qualified_strategy_snapshot(trade_intent: TradeIntent = TradeIntent.BUY, **overrides) -> StrategySnapshot:
    """`tests.titan_protocol.risk_engine._fixtures.make_strategy_snapshot()`
    predates ADR-026 Amendment 1 and has no `trade_intent` parameter --
    this wraps it with `dataclasses.replace()` rather than modifying a
    fixture file shared by several other packages' test suites."""

    snapshot = make_strategy_snapshot(**overrides)
    qualification = dataclasses.replace(snapshot.winning_strategy.qualification, trade_intent=trade_intent)
    winning_strategy = dataclasses.replace(snapshot.winning_strategy, qualification=qualification)
    return dataclasses.replace(snapshot, winning_strategy=winning_strategy, trade_intent=trade_intent)


def make_profile(**overrides) -> TradingProfile:
    defaults = dict(
        profile_id="test_profile",
        description="test profile",
        trading_window=TradingWindow(start_hour_utc=0, end_hour_utc=24),
        session_rules=(),  # empty -> no session filter applied
        risk_profile=RiskEngineConfig(),
        allowed_pairs=("EURUSD", "GBPUSD"),
    )
    defaults.update(overrides)
    return make_custom_profile(**defaults)


def make_bars(count: int = 20, symbol: str = "EURUSD", start: datetime = T0) -> tuple:
    bars = []
    price = 1.1000
    for i in range(count):
        bars.append(Bar(symbol=symbol, timestamp=start - timedelta(hours=count - i), open=price, high=price + 0.0005, low=price - 0.0005, close=price, volume=100.0))
    return tuple(bars)


def _ramp(a: float, b: float, n: int) -> List[float]:
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def make_trending_bars(symbol: str = "EURUSD", start: datetime = T0) -> tuple:
    """A genuine (non-flat) synthetic bar sequence: an early double-
    bottom/double-top consolidation (produces two clustered support and
    two clustered resistance levels, per `structure.py`'s tolerance-based
    clustering) followed by a monotonic staircase uptrend (ascending
    swing highs and lows -- `TrendClassification.TRENDING_UP`, BOS-only
    events, no CHOCH, no volatility expansion/compression). Verified to
    drive the real Evidence -> Strategy chain to a genuine QUALIFIED
    `TrendContinuationStrategy` result with `TradeIntent.BUY`, and a
    composite evidence score comfortably above the Risk Engine's 65-point
    hard gate (ADR-027 Hard Rule 1) -- unlike `make_bars()`'s flat
    synthetic data, which deliberately qualifies no strategy."""
    prices: List[float] = []
    low, high = 1.1000, 1.1050
    prices += _ramp(low, high, 6)
    prices += _ramp(high, low, 6)[1:]
    prices += _ramp(low, high, 6)[1:]
    prices += _ramp(high, low, 6)[1:]

    price = prices[-1]
    for _leg in range(4):
        for _ in range(8):
            price += 0.0020
            prices.append(price)
        for _ in range(4):
            price -= 0.0008
            prices.append(price)

    n = len(prices)
    bars = [
        Bar(symbol=symbol, timestamp=start - timedelta(hours=n - i), open=p, high=p + 0.0005, low=p - 0.0005, close=p, volume=100.0)
        for i, p in enumerate(prices)
    ]
    return tuple(bars)


def make_market_safety_inputs(**overrides) -> MarketSafetyInputs:
    return MarketSafetyInputs(**overrides)


def make_compliance_snapshot(
    pair: str = "EURUSD",
    now: datetime = T0,
    decision: ComplianceDecision = ComplianceDecision.APPROVE,
    original_size_r: float = 1.25,
    approved_size_r: Optional[float] = None,
):
    if approved_size_r is None:
        approved_size_r = 0.0 if decision is ComplianceDecision.REJECT else original_size_r
    reason = "rejected -- test" if decision is ComplianceDecision.REJECT else "approved -- test"
    return build_compliance_snapshot(
        pair=pair, now=now, decision=decision, original_size_r=original_size_r, approved_size_r=approved_size_r,
        reason=reason, triggered_rules=(), warnings=(), compliance_score=100.0, lock_recommendation=None,
    )


class RecordingStub:
    """A duck-typed stand-in for one engine -- records every call and
    returns a fixed, caller-supplied snapshot regardless of input."""

    def __init__(self, snapshot, method_name: str):
        self._snapshot = snapshot
        self._method_name = method_name
        self.call_count = 0
        self.calls: List[tuple] = []
        setattr(self, method_name, self._call)

    def _call(self, *args, **kwargs):
        self.call_count += 1
        self.calls.append((args, kwargs))
        return self._snapshot


def make_stub_evidence_engine(snapshot=None):
    return RecordingStub(snapshot or make_evidence_snapshot(), "evaluate_snapshot")


def make_stub_mi_engine(snapshot=None):
    return RecordingStub(snapshot or make_mi_snapshot(), "evaluate")


def make_stub_strategy_engine(snapshot=None):
    return RecordingStub(snapshot or make_qualified_strategy_snapshot(), "evaluate")


def make_stub_risk_engine(snapshot=None):
    return RecordingStub(snapshot or make_risk_snapshot(), "evaluate")


def make_stub_compliance_engine(snapshot=None):
    return RecordingStub(snapshot or make_compliance_snapshot(), "evaluate")


def make_stub_bridge_submit(error=None) -> Callable:
    calls: List[tuple] = []

    def _submit(command, now):
        calls.append((command, now))
        return error

    _submit.calls = calls
    return _submit


__all__ = [
    "T0",
    "make_config",
    "make_profile",
    "make_bars",
    "make_trending_bars",
    "make_market_safety_inputs",
    "make_compliance_snapshot",
    "make_account_state",
    "make_evidence_snapshot",
    "make_mi_snapshot",
    "make_strategy_snapshot",
    "make_qualified_strategy_snapshot",
    "make_risk_snapshot",
    "RecordingStub",
    "make_stub_evidence_engine",
    "make_stub_mi_engine",
    "make_stub_strategy_engine",
    "make_stub_risk_engine",
    "make_stub_compliance_engine",
    "make_stub_bridge_submit",
]
