"""Shared test-only fixtures for the Validation Engine test suite --
reuses the Risk Engine's, Compliance Engine's, and Research Engine's own
fixture builders for `EvidenceSnapshot`/`MarketIntelligenceSnapshot`/
`StrategySnapshot`/`RiskSnapshot`/`ClosedTrade` (no second, divergent
construction of the same upstream types), and adds a builder for this
engine's own new `HistoricalScenario`/`HistoricalRun`/
`BridgeExecutionRecord`/`ConfigurationRun` types."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from phantom.compliance_engine.explainability import build_compliance_snapshot
from phantom.compliance_engine.models import ComplianceDecision, ComplianceSnapshot
from phantom.risk_engine.models import RiskSnapshot
from phantom.validation_engine.config import ValidationEngineConfig
from phantom.validation_engine.models import (
    BridgeExecutionRecord,
    ConfigurationProfile,
    ConfigurationRun,
    HistoricalRun,
    HistoricalScenario,
    StressScenarioTag,
)
from tests.phantom.compliance_engine._fixtures import make_risk_snapshot
from tests.phantom.research_engine._fixtures import (  # noqa: F401 -- re-exported
    make_executed_trade,
    make_rejected_trade,
    make_repeating_executed_trades,
    make_trade_history,
)
from tests.phantom.risk_engine._fixtures import make_evidence_snapshot, make_mi_snapshot, make_strategy_snapshot

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)  # Friday, London/NY overlap


def make_config(**overrides) -> ValidationEngineConfig:
    return ValidationEngineConfig(**overrides)


def make_compliance_snapshot(
    pair: str = "EURUSD",
    now: datetime = T0,
    decision: ComplianceDecision = ComplianceDecision.APPROVE,
    original_size_r: float = 1.25,
    approved_size_r: Optional[float] = None,
) -> ComplianceSnapshot:
    if approved_size_r is None:
        approved_size_r = 0.0 if decision is ComplianceDecision.REJECT else original_size_r
    reason = "rejected -- test" if decision is ComplianceDecision.REJECT else "approved -- test"
    return build_compliance_snapshot(
        pair=pair, now=now, decision=decision, original_size_r=original_size_r, approved_size_r=approved_size_r,
        reason=reason, triggered_rules=(), warnings=(), compliance_score=100.0, lock_recommendation=None,
    )


def make_scenario(
    scenario_id: str = "SCN-1",
    pair: str = "EURUSD",
    now: datetime = T0,
    approved: bool = True,
    decision: ComplianceDecision = ComplianceDecision.APPROVE,
    risk_snapshot: Optional[RiskSnapshot] = None,
    execution: Optional[BridgeExecutionRecord] = None,
    stress_tag: Optional[StressScenarioTag] = None,
) -> HistoricalScenario:
    risk = risk_snapshot if risk_snapshot is not None else make_risk_snapshot(pair=pair, now=now, approved=approved)
    original_size_r = risk.approved_risk_r if risk.approved else 0.0
    compliance = make_compliance_snapshot(pair=pair, now=now, decision=decision, original_size_r=original_size_r)
    return HistoricalScenario(
        scenario_id=scenario_id, pair=pair, now=now,
        evidence=make_evidence_snapshot(symbol=pair, now=now),
        market_intelligence=make_mi_snapshot(pair=pair, now=now),
        strategy=make_strategy_snapshot(pair=pair, now=now, rejected=not approved),
        risk=risk, compliance=compliance, execution=execution, stress_tag=stress_tag,
    )


def make_execution_record(
    pair: str = "EURUSD",
    was_executed: bool = True,
    approved_size_r: float = 1.25,
    executed_size_r: Optional[float] = None,
    slippage_pips: float = 0.5,
    rejected_by_bridge: bool = False,
    rejection_reason: Optional[str] = None,
    notes: str = "filled at market",
) -> BridgeExecutionRecord:
    return BridgeExecutionRecord(
        pair=pair, was_executed=was_executed, approved_size_r=approved_size_r,
        executed_size_r=executed_size_r if executed_size_r is not None else (approved_size_r if was_executed else 0.0),
        requested_entry_price=1.1000, actual_fill_price=1.1001, slippage_pips=slippage_pips,
        rejected_by_bridge=rejected_by_bridge, rejection_reason=rejection_reason, notes=notes,
    )


def make_run(scenarios: Sequence[HistoricalScenario] = (), research_snapshot: Optional[object] = None, name: str = "test-run") -> HistoricalRun:
    return HistoricalRun(name=name, scenarios=tuple(scenarios), research_snapshot=research_snapshot)


def make_configuration_run(profile: ConfigurationProfile = ConfigurationProfile.BALANCED, trades: Sequence = ()) -> ConfigurationRun:
    return ConfigurationRun(profile=profile, trades=make_trade_history(trades))


__all__ = [
    "T0",
    "make_config",
    "make_compliance_snapshot",
    "make_scenario",
    "make_execution_record",
    "make_run",
    "make_configuration_run",
    "make_evidence_snapshot",
    "make_mi_snapshot",
    "make_strategy_snapshot",
    "make_risk_snapshot",
    "make_executed_trade",
    "make_rejected_trade",
    "make_trade_history",
    "make_repeating_executed_trades",
]
