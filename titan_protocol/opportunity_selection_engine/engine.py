"""Opportunity Selection Engine orchestrator (ADR-037 §4-§6, as corrected
by Amendment 1). Thin composition of `select_winner()` (via the store's
`decide_once()`, so persistence and selection are never called out of
order) plus logging/metrics calls. No public method resembling a
decision API beyond this one purpose-built call.

`opening_range_duration_minutes` is supplied once, at construction --
the same single, global value that already governs every opening
range's own width (`EvidenceEngineConfig.opening_range_duration_minutes`).
This engine has no upstream dependency on `evidence_engine` at all (its
own architecture boundary permits only `titan_protocol.strategy_engine`)
-- Runtime, which already holds `self.evidence_engine.config`, reads
this value once and supplies it here; this engine never invents or
recomputes it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from titan_protocol.strategy_engine.models import SessionName

from .config import OpportunitySelectionEngineConfig
from .logging_sink import log_opportunity_window_result
from .metrics import OpportunitySelectionEngineMetrics
from .models import OpportunityCandidate, SelectionOutcome
from .store import OpportunityWinnerStore


class OpportunitySelectionEngine:
    def __init__(
        self,
        config: OpportunitySelectionEngineConfig,
        store: OpportunityWinnerStore,
        opening_range_duration_minutes: int,
        metrics: Optional[OpportunitySelectionEngineMetrics] = None,
    ) -> None:
        self.config = config
        self._store = store
        self._opening_range_duration_minutes = opening_range_duration_minutes
        self.metrics = metrics

    def evaluate_window(
        self,
        range_start: datetime,
        session_name: SessionName,
        candidates: Tuple[OpportunityCandidate, ...],
        now: datetime,
    ) -> SelectionOutcome:
        winner = self._store.decide_once(
            range_start, session_name, candidates, self.config.tie_tolerance,
            self._opening_range_duration_minutes, now,
        )

        if winner is not None:
            reason = "winner selected"
        elif not candidates:
            reason = "no candidates"
        else:
            reason = "tie within tolerance"

        outcome = SelectionOutcome(winner=winner, reason=reason)

        if self.metrics is not None:
            self.metrics.record_scan()
            if winner is not None:
                self.metrics.record_winner()
            elif not candidates:
                self.metrics.record_empty_candidate_set()
            else:
                self.metrics.record_tie()

        log_opportunity_window_result(range_start, session_name, outcome)
        return outcome


__all__ = ["OpportunitySelectionEngine"]
