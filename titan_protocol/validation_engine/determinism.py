"""Determinism Validation (ADR-030 §5.2): re-running this package's own
verification against the same recorded scenario multiple times must
produce identical results. This never re-invokes the five upstream
engines (ADR-030 Hard Rule 4) -- it guards against non-determinism,
race conditions, floating-point drift, or timing dependencies creeping
into this package's own verification/aggregation code."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .config import ValidationEngineConfig
from .models import DeterminismCheck, DeterminismReport, HistoricalScenario
from .replay import verify_scenario


def check_determinism(scenario: HistoricalScenario, config: ValidationEngineConfig) -> DeterminismCheck:
    runs = [verify_scenario(scenario) for _ in range(config.determinism_repeat_count)]
    first = runs[0]
    mismatches: List[str] = []
    for i, run in enumerate(runs[1:], start=2):
        if run != first:
            mismatches.append(f"run {i} differs from run 1")

    return DeterminismCheck(
        scenario_id=scenario.scenario_id, runs=config.determinism_repeat_count,
        all_identical=not mismatches, mismatches=tuple(mismatches),
    )


def check_determinism_for_run(scenarios: Sequence[HistoricalScenario], config: ValidationEngineConfig) -> DeterminismReport:
    checks: Tuple[DeterminismCheck, ...] = tuple(check_determinism(s, config) for s in scenarios)
    return DeterminismReport(checks=checks, all_deterministic=all(c.all_identical for c in checks))


__all__ = ["check_determinism", "check_determinism_for_run"]
