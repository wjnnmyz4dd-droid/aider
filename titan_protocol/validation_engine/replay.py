"""Historical Replay (ADR-030 §3, §5.1): structural and cross-stage
verification over already-recorded snapshots. This module never
re-invokes the Evidence/Market Intelligence/Strategy/Risk/Compliance
engines' own compute logic (ADR-030 Hard Rule 4) -- it only checks that
the recorded `HistoricalScenario` satisfies the invariants those
engines' own Hard Rules already promise."""

from __future__ import annotations

from typing import List, Tuple

from titan_protocol.compliance_engine.models import ComplianceDecision

from .models import HistoricalScenario, OutputVerification, ScenarioVerification, StageName

_EPSILON = 1e-9


def _verify_evidence(scenario: HistoricalScenario) -> OutputVerification:
    checks: List[str] = []
    failures: List[str] = []

    checks.append("evidence.report.symbol matches scenario.pair")
    if scenario.evidence.report.symbol != scenario.pair:
        failures.append(f"evidence.report.symbol ({scenario.evidence.report.symbol!r}) != pair ({scenario.pair!r})")

    return OutputVerification(stage=StageName.EVIDENCE, passed=not failures, checks=tuple(checks), failures=tuple(failures))


def _verify_market_intelligence(scenario: HistoricalScenario) -> OutputVerification:
    checks: List[str] = []
    failures: List[str] = []

    checks.append("market_intelligence.pair matches scenario.pair")
    if scenario.market_intelligence.pair != scenario.pair:
        failures.append(f"market_intelligence.pair ({scenario.market_intelligence.pair!r}) != pair ({scenario.pair!r})")

    return OutputVerification(
        stage=StageName.MARKET_INTELLIGENCE, passed=not failures, checks=tuple(checks), failures=tuple(failures),
    )


def _verify_strategy(scenario: HistoricalScenario) -> OutputVerification:
    checks: List[str] = []
    failures: List[str] = []
    strategy = scenario.strategy

    checks.append("strategy.pair matches scenario.pair")
    if strategy.pair != scenario.pair:
        failures.append(f"strategy.pair ({strategy.pair!r}) != pair ({scenario.pair!r})")

    checks.append("strategy.rejected is consistent with strategy.winning_strategy")
    if strategy.rejected and strategy.winning_strategy is not None:
        failures.append("strategy.rejected is True but strategy.winning_strategy is set")
    if not strategy.rejected and strategy.winning_strategy is None:
        failures.append("strategy.rejected is False but strategy.winning_strategy is None")

    return OutputVerification(stage=StageName.STRATEGY, passed=not failures, checks=tuple(checks), failures=tuple(failures))


def _verify_risk(scenario: HistoricalScenario) -> OutputVerification:
    checks: List[str] = []
    failures: List[str] = []
    risk = scenario.risk

    checks.append("risk.pair matches scenario.pair")
    if risk.pair != scenario.pair:
        failures.append(f"risk.pair ({risk.pair!r}) != pair ({scenario.pair!r})")

    checks.append("risk.approved is consistent with risk.recommended_position_size")
    if risk.approved and risk.recommended_position_size is None:
        failures.append("risk.approved is True but risk.recommended_position_size is None")
    if not risk.approved and risk.recommended_position_size is not None:
        failures.append("risk.approved is False but risk.recommended_position_size is set")

    checks.append("risk.approved_risk_r is non-negative")
    if risk.approved_risk_r < 0:
        failures.append(f"risk.approved_risk_r is negative ({risk.approved_risk_r})")

    return OutputVerification(stage=StageName.RISK, passed=not failures, checks=tuple(checks), failures=tuple(failures))


def _verify_compliance(scenario: HistoricalScenario) -> OutputVerification:
    checks: List[str] = []
    failures: List[str] = []
    risk, compliance = scenario.risk, scenario.compliance

    checks.append("compliance.pair matches scenario.pair")
    if compliance.pair != scenario.pair:
        failures.append(f"compliance.pair ({compliance.pair!r}) != pair ({scenario.pair!r})")

    expected_original = risk.approved_risk_r if risk.approved else 0.0
    checks.append("compliance.original_size_r reflects risk.approved_risk_r")
    if abs(compliance.original_size_r - expected_original) > _EPSILON:
        failures.append(
            f"compliance.original_size_r ({compliance.original_size_r}) != expected ({expected_original}) "
            f"given risk.approved={risk.approved}"
        )

    checks.append("compliance never increases risk versus its own original_size_r")
    if compliance.approved_size_r > compliance.original_size_r + _EPSILON:
        failures.append(
            f"compliance.approved_size_r ({compliance.approved_size_r}) exceeds "
            f"original_size_r ({compliance.original_size_r})"
        )

    checks.append("compliance.ready_for_bridge implies a non-REJECT decision and positive approved size")
    if compliance.ready_for_bridge:
        if compliance.decision is ComplianceDecision.REJECT or compliance.approved_size_r <= 0:
            failures.append("compliance.ready_for_bridge is True despite REJECT decision or non-positive approved size")

    return OutputVerification(stage=StageName.COMPLIANCE, passed=not failures, checks=tuple(checks), failures=tuple(failures))


def _verify_bridge(scenario: HistoricalScenario) -> OutputVerification:
    checks: List[str] = []
    failures: List[str] = []
    execution = scenario.execution

    if execution is None:
        return OutputVerification(stage=StageName.BRIDGE, passed=True, checks=("no execution record supplied -- skipped",), failures=())

    checks.append("execution.was_executed implies compliance.ready_for_bridge")
    if execution.was_executed and not scenario.compliance.ready_for_bridge:
        failures.append("execution.was_executed is True but compliance.ready_for_bridge is False")

    checks.append("execution.executed_size_r never exceeds execution.approved_size_r")
    if execution.executed_size_r > execution.approved_size_r + _EPSILON:
        failures.append(
            f"execution.executed_size_r ({execution.executed_size_r}) exceeds approved_size_r ({execution.approved_size_r})"
        )

    return OutputVerification(stage=StageName.BRIDGE, passed=not failures, checks=tuple(checks), failures=tuple(failures))


def verify_scenario(scenario: HistoricalScenario) -> ScenarioVerification:
    stage_verifications: Tuple[OutputVerification, ...] = (
        _verify_evidence(scenario),
        _verify_market_intelligence(scenario),
        _verify_strategy(scenario),
        _verify_risk(scenario),
        _verify_compliance(scenario),
        _verify_bridge(scenario),
    )
    return ScenarioVerification(
        scenario_id=scenario.scenario_id, pair=scenario.pair, stage_verifications=stage_verifications,
        passed=all(v.passed for v in stage_verifications),
    )


def verify_run(scenarios) -> Tuple[ScenarioVerification, ...]:
    return tuple(verify_scenario(scenario) for scenario in scenarios)


__all__ = ["verify_scenario", "verify_run"]
