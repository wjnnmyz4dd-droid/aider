"""REASON_CODE_PRESENCE — a generic traceability rule (ADR-004 §5).

A hypothesis with at least one enumerable reason code is more
traceable/auditable than one without. Abstains when `reason_codes` is
empty — there is genuinely nothing for this rule to evaluate, not a
degraded/zero-value case (ADR-004 §8, §12).
"""

from __future__ import annotations

from ...strategy_engine.models import CandidateTrade
from ..config import ScoringEngineConfig
from ..models import RuleContribution, RuleOutcome, ScoringEvidence
from ..rule import ScoringRule, ScoringRuleMetadata


class ReasonCodePresenceRule(ScoringRule):
    _METADATA = ScoringRuleMetadata(
        rule_id="REASON_CODE_PRESENCE",
        version="1.0.0",
        description=(
            "Points proportional to the count of enumerable reason codes "
            "(capped); abstains when no reason code is present."
        ),
        factor="traceability",
    )

    @property
    def metadata(self) -> ScoringRuleMetadata:
        return self._METADATA

    def evaluate(self, candidate: CandidateTrade, config: ScoringEngineConfig) -> RuleContribution:
        weight = config.weight_for(self._METADATA.rule_id)

        if not candidate.reason_codes:
            return RuleContribution(
                rule_id=self._METADATA.rule_id,
                rule_version=self._METADATA.version,
                outcome=RuleOutcome.ABSTAINED,
                points=0.0,
                weight=weight,
                evidence=(),
                detail="no reason codes present",
            )

        countable = candidate.reason_codes[: config.max_countable_evidence_items]
        points = len(countable) * weight

        return RuleContribution(
            rule_id=self._METADATA.rule_id,
            rule_version=self._METADATA.version,
            outcome=RuleOutcome.FIRED,
            points=points,
            weight=weight,
            evidence=tuple(ScoringEvidence("reason_codes", code) for code in countable),
            detail=f"{len(candidate.reason_codes)} reason code(s)",
        )
