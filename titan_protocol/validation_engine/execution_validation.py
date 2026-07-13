"""Execution Validation (ADR-030 §5.12): static consistency checks over
recorded `BridgeExecutionRecord`s. This package never talks to MT5 and
never holds broker credentials (Hard Rule 1) -- it only checks that
what already happened is internally consistent with what Compliance
Engine recorded as approved."""

from __future__ import annotations

from typing import List, Sequence

from .config import ValidationEngineConfig
from .models import ExecutionValidationResult, HistoricalScenario

_EPSILON = 1e-9


def validate_execution(scenarios: Sequence[HistoricalScenario], config: ValidationEngineConfig) -> ExecutionValidationResult:
    violations: List[str] = []
    records_checked = 0

    for scenario in scenarios:
        execution = scenario.execution
        if execution is None:
            continue
        records_checked += 1

        if execution.executed_size_r > execution.approved_size_r + _EPSILON:
            violations.append(
                f"{scenario.scenario_id}: executed_size_r ({execution.executed_size_r}) exceeds "
                f"approved_size_r ({execution.approved_size_r})"
            )

        if execution.was_executed and execution.rejected_by_bridge:
            violations.append(f"{scenario.scenario_id}: execution is marked both executed and rejected_by_bridge")

        if execution.was_executed and not scenario.compliance.ready_for_bridge:
            violations.append(f"{scenario.scenario_id}: executed despite compliance.ready_for_bridge=False")

        if abs(execution.slippage_pips) > config.max_acceptable_slippage_pips:
            violations.append(
                f"{scenario.scenario_id}: slippage ({execution.slippage_pips} pips) exceeds "
                f"the configured maximum ({config.max_acceptable_slippage_pips} pips)"
            )

    return ExecutionValidationResult(records_checked=records_checked, violations=tuple(violations), passed=not violations)


__all__ = ["validate_execution"]
