"""The Execution Validator (ADR-007).

`ExecutionValidator.validate()` is the single entry point for one
`ComplianceDecision`: it always returns exactly one `ExecutionDecision` —
never fewer, never a silent drop (§3). Every check in `checks.py` is
evaluated independently, and every one of them always runs, even once a
REJECT is already certain — so `ExecutionDecision.check_evaluations` is
always the complete audit trail (§6, §10), never a partial one. This
mirrors `compliance_engine.engine`'s "no short-circuit" design, applied
here even more strictly per this task's own explicit instruction, so
`validate()` has no upfront malformed-request short-circuit either
(unlike Risk/Compliance Engine): a missing/mismatched
`ComplianceDecision`/`RiskDecision` is instead caught and reported by the
relevant named checks themselves (`COMPLIANCE_APPROVAL_VALID`,
`RISK_DECISION_CONSISTENT`, `CANDIDATE_INTEGRITY`), keeping the audit
trail uniform for every input, malformed or not.

`checks.py` implements 19 named checks. ADR-007 §6 itself names 11
distinct (non-umbrella) checks: `MARKET_OPEN`, `SYMBOL_TRADABLE`,
`PRICE_VALID`, `SPREAD_UNCHANGED`, `SLIPPAGE_WITHIN_LIMITS`,
`ORDER_SYNCHRONIZED`, `ACCOUNT_SYNCHRONIZED`, `SUFFICIENT_MARGIN`,
`BROKER_CONNECTION_HEALTHY`, `TRADE_NOT_STALE`, `NO_DUPLICATE_REQUEST`
(§7). `COMPLIANCE_APPROVAL_VALID` implements §2's "must be APPROVE"
requirement as its own named check. `RISK_DECISION_CONSISTENT` and
`CANDIDATE_INTEGRITY` implement this task's requested "risk approval
still valid" / "candidate integrity" checks as identity/consistency
cross-checks across the trace chain. `STOP_LOSS_VALID`,
`TAKE_PROFIT_VALID`, `MINIMUM_RR`, `POSITION_SIZING_VALID`, and
`EXISTING_POSITION_VALIDATION` implement this task's remaining requested
checks; none of these five has literal textual grounding in ADR-007 §6
(no upstream ADR through ADR-006 carries a stop-loss/take-profit price
field at all), so each accepts an explicit optional parameter for data no
upstream stage produces — mirroring the same honest, documented Phase 1
limitation `RiskEngine.decide()`'s `stop_distance` parameter already
established. "Final execution eligibility" (the task's 15th requested
check) is represented by `ExecutionDecision.verdict` itself, not a
16th/20th `CheckEvaluation` — a dedicated "did everything else pass"
check would be tautological given every check is already combined by
AND.

`validate()` never mutates `compliance_decision`, `risk_decision`,
`score_result`, or `candidate` — all are read-only, immutable inputs
(§2, §13).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence, Tuple

from ..compliance_engine.models import ComplianceDecision
from ..data_pipeline.models import MarketSnapshot
from ..risk_engine.models import RiskDecision
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade
from . import checks as check_fns
from .config import DEFAULT_CONFIG, EXECUTION_VALIDATOR_VERSION, ExecutionValidatorConfig
from .idempotency_store import IdempotencyStore
from .logging_sink import log_check_evaluation, log_execution_decision, log_rejection
from .metrics import ExecutionValidatorMetrics
from .models import SCHEMA_VERSION, AccountState, BrokerState, ExecutionDecision, Verdict


class ExecutionValidator:
    def __init__(
        self,
        idempotency_store: IdempotencyStore,
        config: ExecutionValidatorConfig = DEFAULT_CONFIG,
        metrics: Optional[ExecutionValidatorMetrics] = None,
    ):
        self.idempotency_store = idempotency_store
        self.config = config
        self.metrics = metrics

    def validate(
        self,
        compliance_decision: Optional[ComplianceDecision],
        risk_decision: Optional[RiskDecision],
        score_result: ScoreResult,
        candidate: CandidateTrade,
        market_snapshot: Optional[MarketSnapshot],
        broker_state: Optional[BrokerState],
        account_state: Optional[AccountState],
        now: datetime,
        reference_price: Optional[float] = None,
        intended_stop_loss: Optional[float] = None,
        intended_take_profit: Optional[float] = None,
    ) -> ExecutionDecision:
        already_seen = self.idempotency_store.has_seen(candidate.candidate_id, now) if candidate.candidate_id else False

        direction = candidate.direction
        symbol = candidate.symbol

        evaluations = (
            check_fns.compliance_approval_valid(compliance_decision),
            check_fns.risk_decision_consistent(risk_decision, compliance_decision),
            check_fns.candidate_integrity(candidate, score_result, risk_decision),
            check_fns.trade_not_stale(risk_decision, now, self.config),
            check_fns.market_open(market_snapshot),
            check_fns.symbol_tradable(broker_state),
            check_fns.price_valid(market_snapshot),
            check_fns.spread_unchanged(market_snapshot, symbol, self.config),
            check_fns.slippage_within_limits(market_snapshot, reference_price, self.config),
            check_fns.order_synchronized(candidate, risk_decision, compliance_decision),
            check_fns.account_synchronized(risk_decision, account_state, self.config),
            check_fns.sufficient_margin(risk_decision, account_state),
            check_fns.broker_connection_healthy(broker_state),
            check_fns.no_duplicate_request(candidate, already_seen),
            check_fns.stop_loss_valid(direction, market_snapshot, intended_stop_loss),
            check_fns.take_profit_valid(direction, market_snapshot, intended_take_profit),
            check_fns.minimum_rr(direction, market_snapshot, intended_stop_loss, intended_take_profit, self.config),
            check_fns.position_sizing_valid(risk_decision),
            check_fns.existing_position_validation(account_state),
        )

        for evaluation in evaluations:
            log_check_evaluation(candidate.candidate_id, candidate.trace_id, evaluation)

        blocking_reasons = tuple(sorted(e.check for e in evaluations if e.blocks))
        warnings = tuple(e.warning for e in evaluations if e.warning is not None)
        verdict = Verdict.REJECT if blocking_reasons else Verdict.APPROVE
        reason_codes = blocking_reasons if blocking_reasons else tuple(sorted(e.check for e in evaluations))

        if verdict == Verdict.APPROVE and candidate.candidate_id:
            self.idempotency_store.record(candidate.candidate_id, now)

        decision = ExecutionDecision(
            schema_version=SCHEMA_VERSION,
            trace_id=candidate.trace_id,
            candidate_id=candidate.candidate_id,
            strategy_id=candidate.strategy_id,
            symbol=symbol,
            timeframe=candidate.timeframe,
            timestamp=candidate.timestamp,
            direction=direction,
            verdict=verdict,
            blocking_reasons=blocking_reasons,
            reason_codes=reason_codes,
            warnings=warnings,
            check_evaluations=evaluations,
            execution_validator_version=EXECUTION_VALIDATOR_VERSION,
        )

        if verdict == Verdict.REJECT:
            for check in blocking_reasons:
                log_rejection(decision.candidate_id, decision.trace_id, check, now, check)
        log_execution_decision(decision)
        if self.metrics is not None:
            self.metrics.record_decision(decision)
        return decision

    def validate_batch(
        self,
        requests: Sequence[
            Tuple[
                Optional[ComplianceDecision],
                Optional[RiskDecision],
                ScoreResult,
                CandidateTrade,
                Optional[MarketSnapshot],
                Optional[BrokerState],
                Optional[AccountState],
                datetime,
                Optional[float],
                Optional[float],
                Optional[float],
            ]
        ],
    ) -> Tuple[ExecutionDecision, ...]:
        return tuple(self.validate(*request) for request in requests)
