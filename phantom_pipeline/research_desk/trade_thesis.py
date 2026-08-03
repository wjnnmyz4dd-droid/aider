"""Trade Thesis Generator (`ADR-021` §3, item 3) — extends
`knowledge.TradeMemoryRecord`'s own why-happened/why-skipped narrative
with institutional framing. Every field is read from the same
already-produced `TradeProvenanceRecord`, never a second, independent
derivation (`ADR-021` §3 table).
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple

from ..analytics.models import OutcomeKind, TradeProvenanceRecord
from ..scanner.models import MarketPhase
from .models import SCHEMA_VERSION, TradeThesis

_BULLISH_PHASES = (MarketPhase.MARKUP, MarketPhase.ACCUMULATION)
_BEARISH_PHASES = (MarketPhase.MARKDOWN, MarketPhase.DISTRIBUTION)


class TradeThesisGenerator:
    def _why_setup_existed(self, record: TradeProvenanceRecord) -> str:
        if record.candidate is None:
            return "No candidate was recorded for this trace."
        parts = [record.candidate.entry_concept, record.candidate.reasoning]
        return " ".join(p for p in parts if p) or "No entry concept recorded."

    def _why_it_qualified(self, record: TradeProvenanceRecord) -> str:
        if record.score_result is None:
            return "No score result was recorded for this trace."
        return (
            f"Scored {record.score_result.overall_score:.2f} — {record.score_result.confidence_rationale}."
        )

    def _why_it_failed_or_succeeded(self, record: TradeProvenanceRecord) -> str:
        outcome = record.final_outcome
        if outcome is None:
            return "No final outcome was recorded for this trace."
        if outcome.outcome_kind == OutcomeKind.REJECTED:
            return f"Rejected at {outcome.rejected_at_stage}: {outcome.rejection_reason}."
        if outcome.outcome_kind == OutcomeKind.OPEN:
            return "Position is still open; no terminal outcome yet."
        pnl = outcome.realized_pnl
        if pnl is None:
            return f"Closed ({outcome.close_reason}) with no recorded PnL."
        result = "succeeded" if pnl > 0 else "failed" if pnl < 0 else "broke even"
        return f"Closed ({outcome.close_reason}), trade {result} with realized PnL {pnl:.2f}."

    def _institutional_context(self, record: TradeProvenanceRecord) -> str:
        observation = record.scanner_observation
        if observation is None:
            return "No scanner observation was recorded; institutional context cannot be derived."
        phase_label = observation.phase.value
        structure_kinds = sorted({s.kind.value for s in observation.structure}) if observation.structure else []
        structure_text = f"with {', '.join(structure_kinds)} structure" if structure_kinds else "with no structural confirmation recorded"
        return f"Market phase was {phase_label} {structure_text} at observation time."

    def _expected_continuation(self, record: TradeProvenanceRecord) -> str:
        observation = record.scanner_observation
        if observation is None:
            return "No scanner observation recorded; continuation expectation cannot be derived."
        if observation.phase in _BULLISH_PHASES:
            return "Continuation upward favored while the MARKUP/ACCUMULATION phase and aligned structure persist."
        if observation.phase in _BEARISH_PHASES:
            return "Continuation downward favored while the MARKDOWN/DISTRIBUTION phase and aligned structure persist."
        return "No clear continuation bias — phase was undetermined or neutral at observation time."

    def _risk_factors(self, record: TradeProvenanceRecord) -> Tuple[str, ...]:
        factors = []
        if record.risk_decision is not None:
            factors.extend(f"binding constraint: {e.constraint}" for e in record.risk_decision.constraint_evaluations if e.binding)
        if record.compliance_decision is not None and record.compliance_decision.blocking_rules:
            factors.extend(f"compliance concern: {rule}" for rule in record.compliance_decision.blocking_rules)
        # ADR-022 Amendment 1 §A1.2 item 5 — reads the already-recorded
        # StatisticalRiskAssessment `record` itself already carries
        # (analytics.TradeProvenanceRecord.statistical_risk_assessment);
        # never computes a new statistical value, only quotes one.
        assessment = record.statistical_risk_assessment
        if assessment is not None:
            factors.append(
                f"statistical risk: {assessment.statistical_recommendation.value} "
                f"(confidence {assessment.confidence_score}, risk of ruin {assessment.risk_of_ruin})"
            )
        return tuple(factors)

    def _lessons_learned(self, record: TradeProvenanceRecord) -> Tuple[str, ...]:
        lessons = []
        outcome = record.final_outcome
        if outcome is not None and outcome.outcome_kind == OutcomeKind.REJECTED:
            lessons.append("A rejection is not a loss — the block prevented an unqualified position from being taken.")
        if outcome is not None and outcome.outcome_kind == OutcomeKind.CLOSED:
            if outcome.mae is not None and outcome.realized_pnl is not None and outcome.mae < 0 and outcome.realized_pnl > 0:
                lessons.append("Trade recovered from adverse excursion before closing profitably — review whether the initial stop was well-placed.")
            if outcome.realized_pnl is not None and outcome.realized_pnl < 0:
                lessons.append("Trade closed at a loss — review whether the entry qualification criteria remain sound for this setup.")
        return tuple(lessons)

    def generate(self, record: TradeProvenanceRecord, now: datetime) -> TradeThesis:
        return TradeThesis(
            schema_version=SCHEMA_VERSION,
            trace_id=record.trace_id,
            why_setup_existed=self._why_setup_existed(record),
            why_it_qualified=self._why_it_qualified(record),
            why_it_failed_or_succeeded=self._why_it_failed_or_succeeded(record),
            institutional_context=self._institutional_context(record),
            expected_continuation=self._expected_continuation(record),
            risk_factors=self._risk_factors(record),
            lessons_learned=self._lessons_learned(record),
            generated_at=now,
        )


__all__ = ["TradeThesisGenerator"]
