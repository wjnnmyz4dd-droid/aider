"""AI Trade Journal (`ADR-021` §3, item 5).

Reuses `knowledge.ExplanationEngine` for risk/execution narrative
(never a second, duplicate explanation implementation) and
`TradeThesisGenerator` for lessons-learned (never re-derived a second
way). `suggested_improvements` is the one genuinely new heuristic this
module adds.

**Read-only after creation** (`ADR-021` Hard Rule 7): `JournalEntry` is a
frozen dataclass; this module defines no update/edit method anywhere —
a correction is a new entry, never a mutation of history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple

from ..analytics.models import OutcomeKind, TradeProvenanceRecord
from ..knowledge import ExplanationEngine
from ..risk_engine.models import RiskTier
from .models import JournalEntry, SCHEMA_VERSION
from .trade_thesis import TradeThesisGenerator


class AITradeJournal:
    def __init__(self, explanation_engine: ExplanationEngine = None, thesis_generator: TradeThesisGenerator = None) -> None:
        self._explanation_engine = explanation_engine or ExplanationEngine()
        self._thesis_generator = thesis_generator or TradeThesisGenerator()

    def _suggested_improvements(self, record: TradeProvenanceRecord) -> Tuple[str, ...]:
        improvements = []
        if record.risk_decision is not None and record.risk_decision.risk_tier in (RiskTier.DEFENSIVE, RiskTier.HALTED):
            improvements.append(
                f"Risk tier was {record.risk_decision.risk_tier.value} (limited by "
                f"{record.risk_decision.limiting_constraint}) — review exposure/correlation limits for this symbol."
            )
        if record.compliance_decision is not None and record.compliance_decision.blocking_rules:
            for rule in record.compliance_decision.blocking_rules:
                improvements.append(f"Compliance blocked on {rule!r} — review whether this should be filtered earlier.")
        if record.execution_decision is not None and record.execution_decision.blocking_reasons:
            for reason in record.execution_decision.blocking_reasons:
                improvements.append(f"Execution blocked on {reason!r} — review for a recurring connectivity/timing issue.")
        outcome = record.final_outcome
        if outcome is not None and outcome.outcome_kind == OutcomeKind.CLOSED and outcome.realized_pnl is not None and outcome.realized_pnl < 0:
            improvements.append("Trade closed at a loss — review entry qualification criteria for this setup.")
        # ADR-022 Amendment 1 §A1.2 item 5 — reads the already-recorded
        # StatisticalRiskAssessment `record` itself already carries; never
        # computes a new statistical value, only quotes one.
        assessment = record.statistical_risk_assessment
        if assessment is not None and assessment.statistical_recommendation.value != "NORMAL_RISK":
            improvements.append(
                f"Statistical Risk Manager recommended {assessment.statistical_recommendation.value} "
                f"for this trade — review whether reduced sizing would have been warranted."
            )
        return tuple(improvements)

    def create_entry(self, record: TradeProvenanceRecord, now: datetime) -> JournalEntry:
        why_happened, why_skipped, _rule_explanations, _ai_explanation = self._explanation_engine.explain_trade(record)
        entry_reason = why_happened or why_skipped or "No entry narrative available."
        risk_reason = self._explanation_engine.explain_risk_decision(record.risk_decision)
        execution_quality = self._explanation_engine.explain_execution_decision(record.execution_decision)
        compliance_decision = record.compliance_decision.verdict.value if record.compliance_decision is not None else "UNKNOWN"

        outcome = record.final_outcome
        exit_reason = outcome.close_reason if outcome is not None else None
        profit_or_loss = outcome.realized_pnl if outcome is not None else None

        thesis = self._thesis_generator.generate(record, now)

        return JournalEntry(
            schema_version=SCHEMA_VERSION,
            trace_id=record.trace_id,
            entry_reason=entry_reason,
            risk_reason=risk_reason,
            compliance_decision=compliance_decision,
            execution_quality=execution_quality,
            exit_reason=exit_reason,
            profit_or_loss=profit_or_loss,
            lessons_learned=thesis.lessons_learned,
            suggested_improvements=self._suggested_improvements(record),
            created_at=now,
        )


__all__ = ["AITradeJournal"]
