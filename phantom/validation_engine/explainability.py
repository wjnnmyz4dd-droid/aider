"""Explainability Validation (ADR-030 §5.3): verify every named engine
explains its output -- Evidence, Strategy, Risk, Compliance, Bridge,
Research (the task's own list; Market Intelligence is deliberately not
included, even though it carries its own `MarketIntelligenceExplanation`
-- ADR-030 §5.3). Missing explanation = validation failure."""

from __future__ import annotations

from typing import List, Sequence

from .models import ExplainabilityCheck, ExplainabilityReport, HistoricalRun, HistoricalScenario, StageName


def _check_evidence(scenarios: Sequence[HistoricalScenario]) -> ExplainabilityCheck:
    missing = [s.scenario_id for s in scenarios if not s.evidence.report.confidence_explanation]
    return ExplainabilityCheck(
        stage=StageName.EVIDENCE, has_explanation=not missing,
        detail="all scenarios carry a confidence_explanation" if not missing else f"missing in: {missing}",
    )


def _check_strategy(scenarios: Sequence[HistoricalScenario]) -> ExplainabilityCheck:
    missing = []
    for s in scenarios:
        strategy = s.strategy
        if strategy.rejected:
            if not strategy.rejection_reason:
                missing.append(s.scenario_id)
        elif not strategy.supporting_evidence_summary or not strategy.supporting_market_intelligence_summary:
            missing.append(s.scenario_id)
    return ExplainabilityCheck(
        stage=StageName.STRATEGY, has_explanation=not missing,
        detail="all scenarios carry a strategy explanation" if not missing else f"missing in: {missing}",
    )


def _check_risk(scenarios: Sequence[HistoricalScenario]) -> ExplainabilityCheck:
    missing = []
    for s in scenarios:
        risk = s.risk
        if risk.approved:
            if not risk.reasons:
                missing.append(s.scenario_id)
        elif risk.rejection_reason is None:
            missing.append(s.scenario_id)
    return ExplainabilityCheck(
        stage=StageName.RISK, has_explanation=not missing,
        detail="all scenarios carry a risk explanation" if not missing else f"missing in: {missing}",
    )


def _check_compliance(scenarios: Sequence[HistoricalScenario]) -> ExplainabilityCheck:
    missing = [s.scenario_id for s in scenarios if not s.compliance.reason]
    return ExplainabilityCheck(
        stage=StageName.COMPLIANCE, has_explanation=not missing,
        detail="all scenarios carry a compliance reason" if not missing else f"missing in: {missing}",
    )


def _check_bridge(scenarios: Sequence[HistoricalScenario]) -> ExplainabilityCheck:
    missing = []
    for s in scenarios:
        execution = s.execution
        if execution is None:
            continue
        if execution.rejected_by_bridge and not execution.rejection_reason:
            missing.append(s.scenario_id)
        if not execution.was_executed and not execution.rejected_by_bridge and not execution.notes:
            missing.append(s.scenario_id)
    return ExplainabilityCheck(
        stage=StageName.BRIDGE, has_explanation=not missing,
        detail="all supplied execution records carry an explanation" if not missing else f"missing in: {missing}",
    )


def _check_research(run: HistoricalRun) -> ExplainabilityCheck:
    if run.research_snapshot is None:
        return ExplainabilityCheck(stage=StageName.RESEARCH, has_explanation=True, detail="no research snapshot supplied -- skipped")

    missing = [i for i, r in enumerate(run.research_snapshot.recommendations) if not r.text]
    return ExplainabilityCheck(
        stage=StageName.RESEARCH, has_explanation=not missing,
        detail="every recommendation carries text" if not missing else f"empty recommendation text at indices: {missing}",
    )


def build_explainability_report(run: HistoricalRun) -> ExplainabilityReport:
    checks: List[ExplainabilityCheck] = [
        _check_evidence(run.scenarios),
        _check_strategy(run.scenarios),
        _check_risk(run.scenarios),
        _check_compliance(run.scenarios),
        _check_bridge(run.scenarios),
        _check_research(run),
    ]
    return ExplainabilityReport(checks=tuple(checks), all_explained=all(c.has_explanation for c in checks))


__all__ = ["build_explainability_report"]
