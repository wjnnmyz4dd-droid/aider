"""DIRECTIONAL_CLARITY — a generic directional-clarity rule (ADR-004 §5).

A hypothesis with a clear UP/DOWN direction is more actionable than a
NEUTRAL one — still a structural fact about the hypothesis itself, never
a market-edge claim. Abstains when direction is UNKNOWN: there is no
directional information for this rule to evaluate at all (ADR-004 §8).
"""

from __future__ import annotations

from ...scanner.models import Direction
from ...strategy_engine.models import CandidateTrade
from ..config import ScoringEngineConfig
from ..models import RuleContribution, RuleOutcome
from ..rule import ScoringRule, ScoringRuleMetadata


class DirectionalClarityRule(ScoringRule):
    _METADATA = ScoringRuleMetadata(
        rule_id="DIRECTIONAL_CLARITY",
        version="1.0.0",
        description=(
            "Flat points when direction is UP or DOWN, zero when NEUTRAL; "
            "abstains when direction is UNKNOWN."
        ),
        factor="directional_clarity",
    )

    @property
    def metadata(self) -> ScoringRuleMetadata:
        return self._METADATA

    def evaluate(self, candidate: CandidateTrade, config: ScoringEngineConfig) -> RuleContribution:
        weight = config.weight_for(self._METADATA.rule_id)

        if candidate.direction == Direction.UNKNOWN:
            return RuleContribution(
                rule_id=self._METADATA.rule_id,
                rule_version=self._METADATA.version,
                outcome=RuleOutcome.ABSTAINED,
                points=0.0,
                weight=weight,
                evidence=(),
                detail="direction is UNKNOWN",
            )

        is_directional = candidate.direction in (Direction.UP, Direction.DOWN)
        points = weight if is_directional else 0.0

        return RuleContribution(
            rule_id=self._METADATA.rule_id,
            rule_version=self._METADATA.version,
            outcome=RuleOutcome.FIRED,
            points=points,
            weight=weight,
            evidence=(),
            detail=f"direction={candidate.direction.value}",
        )
