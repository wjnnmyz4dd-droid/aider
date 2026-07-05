"""The Scoring Engine (ADR-004).

`ScoringEngine.score()` is the single entry point for one `CandidateTrade`:
it always returns exactly one `ScoreResult` or one `ScoringFailureRecord`
— never fewer, never a silent drop (§7). `score_batch()` maps `score()`
independently over a sequence of candidates: each candidate's result is
identical whether computed alone or alongside any number of others (§2,
§7) — there is no shared state between calls, so a batch is exactly the
sum of its independent parts.

A `CandidateTrade` with an incompatible `schema_version`, or one that
fails basic structural validation, fails closed with a
`ScoringFailureRecord` for that candidate only (§4, §8) — no rule is even
invoked. Each scoring rule is then invoked inside a try/except: an
exception is caught, logged, and isolated at the rule boundary (§8) — it
never propagates to crash the engine, affect another rule, or affect
another candidate's scoring in the same batch.

Ranking (`ranking.rank_scores`) is a separate, read-only operation over
already-computed `ScoreResult`s — it is never called from within
`score()`/`score_batch()`, so ranking can never influence score
computation (§7, §9, §13).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple, Union

from ..strategy_engine.models import CandidateTrade
from .config import DEFAULT_CONFIG, SCORING_ENGINE_VERSION, ScoringEngineConfig
from .logging_sink import log_rule_execution, log_score_result, log_scoring_failure_record
from .metrics import ScoringEngineMetrics
from .models import (
    SCHEMA_VERSION,
    FactorBreakdown,
    RuleContribution,
    RuleOutcome,
    ScoreResult,
    ScoringFailureRecord,
)
from .registry import ScoringRuleRegistry

SUPPORTED_CANDIDATE_SCHEMA_VERSIONS = (1,)


class ScoringEngine:
    def __init__(
        self,
        registry: ScoringRuleRegistry,
        config: ScoringEngineConfig = DEFAULT_CONFIG,
        metrics: Optional[ScoringEngineMetrics] = None,
    ):
        self.registry = registry
        self.config = config
        self.metrics = metrics

    def score(self, candidate: CandidateTrade) -> Union[ScoreResult, ScoringFailureRecord]:
        failure_reason = self._validate(candidate)
        if failure_reason is not None:
            record = ScoringFailureRecord(
                schema_version=SCHEMA_VERSION,
                trace_id=candidate.trace_id,
                candidate_id=candidate.candidate_id,
                strategy_id=candidate.strategy_id,
                reason=failure_reason,
                scoring_version=SCORING_ENGINE_VERSION,
            )
            log_scoring_failure_record(record)
            if self.metrics is not None:
                self.metrics.record_failure_record(record)
            return record

        rule_contributions = self._evaluate_rules(candidate)

        overall_score = sum(
            rc.points for rc in rule_contributions if rc.outcome == RuleOutcome.FIRED
        )
        factor_breakdown = self._build_factor_breakdown(rule_contributions)
        confidence_rationale = self._build_confidence_rationale(rule_contributions, overall_score)

        result = ScoreResult(
            schema_version=SCHEMA_VERSION,
            trace_id=candidate.trace_id,
            candidate_id=candidate.candidate_id,
            strategy_id=candidate.strategy_id,
            symbol=candidate.symbol,
            timeframe=candidate.timeframe,
            timestamp=candidate.timestamp,
            overall_score=overall_score,
            factor_breakdown=factor_breakdown,
            rule_contributions=rule_contributions,
            confidence_rationale=confidence_rationale,
            scoring_version=SCORING_ENGINE_VERSION,
        )
        log_score_result(result)
        if self.metrics is not None:
            self.metrics.record_score_result(result)
        return result

    def score_batch(
        self, candidates: Sequence[CandidateTrade]
    ) -> Tuple[Union[ScoreResult, ScoringFailureRecord], ...]:
        return tuple(self.score(candidate) for candidate in candidates)

    def _validate(self, candidate: CandidateTrade) -> Optional[str]:
        if candidate.schema_version not in SUPPORTED_CANDIDATE_SCHEMA_VERSIONS:
            return "unsupported_schema_version"
        if not candidate.symbol or not candidate.strategy_id or not candidate.candidate_id:
            return "malformed_candidate"
        return None

    def _evaluate_rules(self, candidate: CandidateTrade) -> Tuple[RuleContribution, ...]:
        contributions: List[RuleContribution] = []
        for rule in self.registry.rules:
            rule_id = rule.metadata.rule_id

            if not self.config.is_enabled(rule_id):
                contribution = RuleContribution(
                    rule_id=rule_id,
                    rule_version=rule.metadata.version,
                    outcome=RuleOutcome.ABSTAINED,
                    points=0.0,
                    weight=self.config.weight_for(rule_id),
                    evidence=(),
                    detail="disabled",
                )
            else:
                try:
                    contribution = rule.evaluate(candidate, self.config)
                except Exception as exc:
                    contribution = RuleContribution(
                        rule_id=rule_id,
                        rule_version=rule.metadata.version,
                        outcome=RuleOutcome.FAILED,
                        points=0.0,
                        weight=self.config.weight_for(rule_id),
                        evidence=(),
                        detail=repr(exc),
                    )

            log_rule_execution(candidate.candidate_id, candidate.trace_id, contribution)
            if self.metrics is not None:
                self.metrics.record_rule_outcome(contribution)
            contributions.append(contribution)

        return tuple(contributions)

    def _build_factor_breakdown(
        self, rule_contributions: Sequence[RuleContribution]
    ) -> Tuple[FactorBreakdown, ...]:
        factor_by_rule_id = self.registry.factor_by_rule_id
        subtotals: Dict[str, float] = {}
        rule_ids_by_factor: Dict[str, List[str]] = {}

        for contribution in rule_contributions:
            factor = factor_by_rule_id.get(contribution.rule_id, "unknown")
            subtotals[factor] = subtotals.get(factor, 0.0) + contribution.points
            rule_ids_by_factor.setdefault(factor, []).append(contribution.rule_id)

        return tuple(
            FactorBreakdown(factor=factor, subtotal=subtotals[factor], rule_ids=tuple(rule_ids))
            for factor, rule_ids in sorted(rule_ids_by_factor.items())
        )

    def _build_confidence_rationale(
        self, rule_contributions: Sequence[RuleContribution], overall_score: float
    ) -> str:
        fired = sum(1 for rc in rule_contributions if rc.outcome == RuleOutcome.FIRED)
        abstained = sum(1 for rc in rule_contributions if rc.outcome == RuleOutcome.ABSTAINED)
        failed = sum(1 for rc in rule_contributions if rc.outcome == RuleOutcome.FAILED)
        total = len(rule_contributions)
        return (
            f"{fired} of {total} rule(s) fired ({abstained} abstained, {failed} failed); "
            f"overall_score={overall_score:.2f}"
        )
