"""The Risk Engine (ADR-005).

`RiskEngine.decide()` is the single entry point for one `ScoreResult`: it
always returns exactly one `RiskDecision` — never fewer, never a silent
drop (§3). Unlike Scoring Engine's `ScoringFailureRecord`, there is no
separate failure-record type here: per ADR-005 §3, a candidate the engine
cannot evaluate still receives a `RiskDecision`, with zero risk and an
explicit reason — the fail-closed path and the happy path share one type.

Every constraint in `constraints.py` is evaluated independently; the
awarded risk is the **minimum** across all of them (§6) — never a pick of
one constraint over another, and never a chain of successive
multiplications that could compound past the per-trade ceiling. `decide()`
never mutates `score_result`, `candidate`, or `observation` — all three
are read-only, immutable inputs (§2, §19).

`decide_batch()` maps `decide()` independently over a sequence of
requests: there is no shared state between calls, so a batch is exactly
the sum of its independent parts, mirroring Scoring Engine's own
`score_batch()` guarantee.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from ..scanner.models import ScannerObservation
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade
from . import constraints as constraint_fns
from .config import DEFAULT_CONFIG, RISK_ENGINE_VERSION, RiskEngineConfig
from .logging_sink import log_constraint_evaluation, log_fail_closed, log_risk_decision
from .metrics import RiskEngineMetrics
from .models import SCHEMA_VERSION, AccountState, ConstraintEvaluation, RiskDecision, RiskTier

SUPPORTED_SCORE_RESULT_SCHEMA_VERSIONS = (1,)


class RiskEngine:
    def __init__(
        self,
        config: RiskEngineConfig = DEFAULT_CONFIG,
        metrics: Optional[RiskEngineMetrics] = None,
    ):
        self.config = config
        self.metrics = metrics

    def decide(
        self,
        score_result: ScoreResult,
        candidate: CandidateTrade,
        observation: ScannerObservation,
        account_state: Optional[AccountState],
        stop_distance: Optional[float] = None,
    ) -> RiskDecision:
        failure_reason = self._validate(score_result, candidate)
        if failure_reason is None and (
            account_state is None or account_state.equity is None or account_state.equity <= 0
        ):
            failure_reason = "missing_account_state"

        if failure_reason is not None:
            decision = self._zero_decision(score_result, candidate, failure_reason)
            log_fail_closed(decision.candidate_id, decision.trace_id, failure_reason)
            log_risk_decision(decision)
            if self.metrics is not None:
                self.metrics.record_decision(decision)
            return decision

        evaluations = self._evaluate_constraints(candidate, observation, account_state)

        min_value = min(e.allowed_risk_percent for e in evaluations)
        evaluations = tuple(
            ConstraintEvaluation(e.constraint, e.allowed_risk_percent, e.allowed_risk_percent == min_value, e.detail)
            for e in evaluations
        )
        for evaluation in evaluations:
            log_constraint_evaluation(candidate.candidate_id, score_result.trace_id, evaluation)

        binding_names = tuple(sorted(e.constraint for e in evaluations if e.binding))
        limiting_constraint = "+".join(binding_names) if binding_names else "NONE"

        approved_risk_percent = min_value
        approved_risk_amount = account_state.equity * approved_risk_percent / 100.0

        lot_size = None
        if stop_distance is not None and stop_distance > 0 and approved_risk_amount > 0:
            lot_size = approved_risk_amount / stop_distance

        risk_tier = self._tier(approved_risk_percent)
        reason_codes = binding_names if binding_names else ("nominal",)

        decision = RiskDecision(
            schema_version=SCHEMA_VERSION,
            trace_id=score_result.trace_id,
            candidate_id=score_result.candidate_id,
            strategy_id=score_result.strategy_id,
            symbol=score_result.symbol,
            timeframe=score_result.timeframe,
            timestamp=score_result.timestamp,
            direction=candidate.direction,
            approved_risk_percent=approved_risk_percent,
            approved_risk_amount=approved_risk_amount,
            lot_size=lot_size,
            risk_tier=risk_tier,
            limiting_constraint=limiting_constraint,
            constraint_evaluations=evaluations,
            reason_codes=reason_codes,
            risk_engine_version=RISK_ENGINE_VERSION,
        )
        log_risk_decision(decision)
        if self.metrics is not None:
            self.metrics.record_decision(decision)
        return decision

    def decide_batch(
        self,
        requests: Sequence[
            Tuple[ScoreResult, CandidateTrade, ScannerObservation, Optional[AccountState], Optional[float]]
        ],
    ) -> Tuple[RiskDecision, ...]:
        return tuple(self.decide(*request) for request in requests)

    def _validate(self, score_result: ScoreResult, candidate: CandidateTrade) -> Optional[str]:
        if score_result.schema_version not in SUPPORTED_SCORE_RESULT_SCHEMA_VERSIONS:
            return "unsupported_schema_version"
        if not score_result.candidate_id or not score_result.strategy_id or not score_result.symbol:
            return "malformed_score_result"
        if (
            candidate.trace_id != score_result.trace_id
            or candidate.candidate_id != score_result.candidate_id
        ):
            return "candidate_score_mismatch"
        return None

    def _evaluate_constraints(
        self,
        candidate: CandidateTrade,
        observation: ScannerObservation,
        account_state: AccountState,
    ) -> Tuple[ConstraintEvaluation, ...]:
        return (
            constraint_fns.per_trade_ceiling(self.config),
            constraint_fns.daily_budget(account_state, self.config),
            constraint_fns.portfolio_heat(account_state, self.config),
            constraint_fns.currency_exposure(account_state, candidate.symbol, self.config),
            constraint_fns.correlation_exposure(account_state, candidate.symbol, self.config),
            constraint_fns.volatility_adjustment(observation, self.config),
            constraint_fns.loss_streak_adjustment(account_state, self.config),
            constraint_fns.drawdown_scaling(account_state, self.config),
        )

    def _tier(self, approved_risk_percent: float) -> RiskTier:
        if approved_risk_percent <= 0.0:
            return RiskTier.HALTED
        if approved_risk_percent >= self.config.max_risk_percent_per_trade:
            return RiskTier.NORMAL
        return RiskTier.DEFENSIVE

    def _zero_decision(
        self, score_result: ScoreResult, candidate: CandidateTrade, reason: str
    ) -> RiskDecision:
        return RiskDecision(
            schema_version=SCHEMA_VERSION,
            trace_id=score_result.trace_id,
            candidate_id=score_result.candidate_id,
            strategy_id=score_result.strategy_id,
            symbol=score_result.symbol,
            timeframe=score_result.timeframe,
            timestamp=score_result.timestamp,
            direction=candidate.direction,
            approved_risk_percent=0.0,
            approved_risk_amount=0.0,
            lot_size=None,
            risk_tier=RiskTier.HALTED,
            limiting_constraint=reason,
            constraint_evaluations=(),
            reason_codes=(reason,),
            risk_engine_version=RISK_ENGINE_VERSION,
        )
