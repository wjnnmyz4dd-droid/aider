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

from phantom.compliance_engine.explainability import build_compliance_snapshot
from phantom.compliance_engine.models import ComplianceDecision
from phantom.evidence_engine.models import Bar
from phantom.market_intelligence.models import MarketSafetyInputs
from phantom.risk_engine.config import RiskEngineConfig
from phantom.runtime.config import RuntimeConfig
from phantom.runtime.models import TradingProfile, TradingWindow
from phantom.runtime.profiles import make_custom_profile
from phantom.strategy_engine.models import StrategySnapshot, TradeIntent
from tests.phantom.compliance_engine._fixtures import make_account_state, make_risk_snapshot
from tests.phantom.risk_engine._fixtures import make_evidence_snapshot, make_mi_snapshot, make_strategy_snapshot

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap, hour 13


def make_config(**overrides) -> RuntimeConfig:
    return RuntimeConfig(**overrides)


def make_qualified_strategy_snapshot(trade_intent: TradeIntent = TradeIntent.BUY, **overrides) -> StrategySnapshot:
    """`tests.phantom.risk_engine._fixtures.make_strategy_snapshot()`
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
