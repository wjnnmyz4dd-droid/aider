"""Scoring-Engine-only metrics surface (ADR-004 §10, §13).

Export-only: recording a metric has zero effect on any returned
`ScoreResult`/`ScoringFailureRecord` — the same "additive, changes
nothing" discipline `phantom_pipeline.scanner.metrics` and
`phantom_pipeline.strategy_engine.metrics` already established. No
Dashboard, no Prometheus, no Analytics here — this is the Scoring
Engine's own metric surface only.
"""

from __future__ import annotations

from typing import Dict, Tuple

from .models import RuleContribution, ScoreResult, ScoringFailureRecord


class ScoringEngineMetrics:
    def __init__(self) -> None:
        self._score_results_total: Dict[str, int] = {}
        self._failure_records_total: Dict[str, int] = {}
        self._rule_outcomes_total: Dict[Tuple[str, str], int] = {}

    def record_score_result(self, result: ScoreResult) -> None:
        self._score_results_total[result.strategy_id] = (
            self._score_results_total.get(result.strategy_id, 0) + 1
        )

    def record_failure_record(self, record: ScoringFailureRecord) -> None:
        self._failure_records_total[record.reason] = (
            self._failure_records_total.get(record.reason, 0) + 1
        )

    def record_rule_outcome(self, contribution: RuleContribution) -> None:
        key = (contribution.rule_id, contribution.outcome.value)
        self._rule_outcomes_total[key] = self._rule_outcomes_total.get(key, 0) + 1

    @property
    def score_results_total(self) -> Dict[str, int]:
        return dict(self._score_results_total)

    @property
    def failure_records_total(self) -> Dict[str, int]:
        return dict(self._failure_records_total)

    @property
    def rule_outcomes_total(self) -> Dict[Tuple[str, str], int]:
        return dict(self._rule_outcomes_total)
