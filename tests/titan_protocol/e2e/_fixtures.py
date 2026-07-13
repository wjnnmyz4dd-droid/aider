"""Shared fixtures for Phase 3B's broader Runtime+Reliability recovery
suite -- reuses `tests.titan_protocol.runtime._fixtures` for the real/stub
engines and `tests.titan_protocol.reliability._fixtures` for the Reliability
config, rather than a second, divergent construction of either."""

from __future__ import annotations

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from tests.titan_protocol.runtime._fixtures import (  # noqa: F401
    T0,
    make_account_state,
    make_bars,
    make_config,
    make_market_safety_inputs,
    make_profile,
    make_qualified_strategy_snapshot,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
    make_trending_bars,
)


class RaisingStub:
    """A duck-typed stand-in that always raises -- the deterministic way
    to drive a real `RuntimeOrchestrator.run_cycle_for_pair()` call to a
    genuine `CycleOutcome.FAILED` (mirrors `test_failover.py`'s own
    `_RaisingStub`, reused here rather than redefined a second time)."""

    def evaluate(self, *args, **kwargs):
        raise RuntimeError("simulated engine failure")

    evaluate_snapshot = evaluate


def make_strategy_config() -> StrategyEngineConfig:
    return StrategyEngineConfig()


def make_compliance_config() -> ComplianceEngineConfig:
    return ComplianceEngineConfig()


__all__ = [
    "T0",
    "make_account_state",
    "make_bars",
    "make_config",
    "make_market_safety_inputs",
    "make_profile",
    "make_qualified_strategy_snapshot",
    "make_stub_bridge_submit",
    "make_stub_compliance_engine",
    "make_stub_evidence_engine",
    "make_stub_mi_engine",
    "make_stub_risk_engine",
    "make_stub_strategy_engine",
    "make_trending_bars",
    "RaisingStub",
    "make_strategy_config",
    "make_compliance_config",
]
