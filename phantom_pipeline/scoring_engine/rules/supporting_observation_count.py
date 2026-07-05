"""SUPPORTING_OBSERVATION_COUNT — a generic evidence-strength rule
(ADR-004 §5).

A hypothesis backed by more Scanner-fact references is more explainable
and auditable — a structural completeness signal, not a claim about
market edge. Never abstains: `supporting_observations` is always present
on a well-formed `CandidateTrade` (possibly empty, legitimately scoring
zero).
"""

from __future__ import annotations

from ...strategy_engine.models import CandidateTrade
from ..config import ScoringEngineConfig
from ..models import RuleContribution, RuleOutcome, ScoringEvidence
from ..rule import ScoringRule, ScoringRuleMetadata


class SupportingObservationCountRule(ScoringRule):
    _METADATA = ScoringRuleMetadata(
        rule_id="SUPPORTING_OBSERVATION_COUNT",
        version="1.0.0",
        description=(
            "Points proportional to the count of supporting Scanner-fact "
            "references (capped), rewarding a more evidenced hypothesis."
        ),
        factor="evidence_strength",
    )

    @property
    def metadata(self) -> ScoringRuleMetadata:
        return self._METADATA

    def evaluate(self, candidate: CandidateTrade, config: ScoringEngineConfig) -> RuleContribution:
        weight = config.weight_for(self._METADATA.rule_id)
        countable = candidate.supporting_observations[: config.max_countable_evidence_items]
        points = len(countable) * weight

        return RuleContribution(
            rule_id=self._METADATA.rule_id,
            rule_version=self._METADATA.version,
            outcome=RuleOutcome.FIRED,
            points=points,
            weight=weight,
            evidence=tuple(
                ScoringEvidence("supporting_observations", f"{so.field}: {so.detail}")
                for so in countable
            ),
            detail=f"{len(candidate.supporting_observations)} supporting observation(s)",
        )
