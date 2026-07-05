"""Strategy-Engine-only metrics surface (ADR-003 §12).

Export-only: recording a metric has zero effect on any returned
`CandidateTrade` — the same "additive, changes nothing" discipline
`phantom_pipeline.scanner.metrics` already established. No Dashboard, no
Prometheus, no Analytics here — this is the Strategy Engine's own metric
surface only.
"""

from __future__ import annotations

from typing import Dict, Tuple

from .models import CandidateTrade


class StrategyEngineMetrics:
    def __init__(self) -> None:
        self._candidates_total: Dict[Tuple[str, str, str], int] = {}
        self._failures_total: Dict[str, int] = {}
        self._abstentions_total: Dict[str, int] = {}
        self._no_hypothesis_scans_total: Dict[str, int] = {}

    def record_candidate(self, candidate: CandidateTrade) -> None:
        key = (candidate.strategy_id, candidate.direction.value, candidate.symbol)
        self._candidates_total[key] = self._candidates_total.get(key, 0) + 1

    def record_failure(self, strategy_id: str) -> None:
        self._failures_total[strategy_id] = self._failures_total.get(strategy_id, 0) + 1

    def record_abstention(self, strategy_id: str) -> None:
        self._abstentions_total[strategy_id] = self._abstentions_total.get(strategy_id, 0) + 1

    def record_no_hypothesis_scan(self, data_quality_flag: str) -> None:
        """A whole call short-circuited on a non-nominal `data_quality_flag`
        before any playbook ran — counted by flag value (ADR-003 §12)."""
        self._no_hypothesis_scans_total[data_quality_flag] = (
            self._no_hypothesis_scans_total.get(data_quality_flag, 0) + 1
        )

    @property
    def candidates_total(self) -> Dict[Tuple[str, str, str], int]:
        return dict(self._candidates_total)

    @property
    def failures_total(self) -> Dict[str, int]:
        return dict(self._failures_total)

    @property
    def abstentions_total(self) -> Dict[str, int]:
        return dict(self._abstentions_total)

    @property
    def no_hypothesis_scans_total(self) -> Dict[str, int]:
        return dict(self._no_hypothesis_scans_total)
