"""Opportunity Selection Engine orchestrator (ADR-037 §4-§6, as corrected
by Amendment 1). Thin composition of `select_winner()` (via the store's
`decide_once()`, so persistence and selection are never called out of
order) plus logging/metrics calls. No public method resembling a
decision API beyond this one purpose-built call.

**"Genuinely superseded" observability (ADR-037 §12, corrected):** the
store (`OpportunityWinnerStore`) intentionally owns no notion of opening-
range lifecycle -- it is keyed purely on `range_start`, already unique
per calendar day and anchor (§8), which structurally prevents an older
opportunity from ever contaminating a newer one. This engine is the
correct, minimal place to observe the *session*-level relationship §12
actually asks for ("a persisted winner from a range that should already
be closed"): the only additional fact needed is "has this session_name
already been asked about a newer `range_start`" -- information this
engine already receives on every call and the store deliberately does
not need. `_latest_range_start_by_session` is a best-effort, in-memory-
only, non-persisted high-water-mark per `SessionName`, purely for this
one log signal; it never gates, blocks, or alters `decide_once()`'s
result. A restart simply resets it to empty and tracking resumes from
that point on -- identical in spirit to this package's other best-effort,
non-authoritative observability state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple

from titan_protocol.strategy_engine.models import SessionName

from .config import OpportunitySelectionEngineConfig
from .logging_sink import log_opportunity_window_result, log_superseded_opportunity_window
from .metrics import OpportunitySelectionEngineMetrics
from .models import OpportunityCandidate, SelectionOutcome
from .store import OpportunityWinnerStore


class OpportunitySelectionEngine:
    def __init__(
        self,
        config: OpportunitySelectionEngineConfig,
        store: OpportunityWinnerStore,
        metrics: Optional[OpportunitySelectionEngineMetrics] = None,
    ) -> None:
        self.config = config
        self._store = store
        self.metrics = metrics
        self._latest_range_start_by_session: Dict[SessionName, datetime] = {}

    def evaluate_window(
        self,
        range_start: datetime,
        session_name: SessionName,
        candidates: Tuple[OpportunityCandidate, ...],
        now: datetime,
    ) -> SelectionOutcome:
        latest_seen = self._latest_range_start_by_session.get(session_name)
        if latest_seen is not None and range_start < latest_seen:
            # A genuinely older opportunity for this session is being
            # asked about after a newer one has already been current --
            # never gates `decide_once()`, purely observational.
            log_superseded_opportunity_window(range_start, session_name, latest_seen)
        elif latest_seen is None or range_start > latest_seen:
            self._latest_range_start_by_session[session_name] = range_start

        winner = self._store.decide_once(range_start, session_name, candidates, self.config.tie_tolerance, now)

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
