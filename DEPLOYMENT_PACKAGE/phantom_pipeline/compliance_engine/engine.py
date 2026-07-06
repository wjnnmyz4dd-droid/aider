"""The Compliance Engine (ADR-006).

`ComplianceEngine.evaluate()` is the single entry point for one
`RiskDecision`: it always returns exactly one `ComplianceDecision` —
never fewer, never a silent drop (§3). Every check in `checks.py` is
evaluated independently and every one of them is always run, even once a
BLOCK is already certain — so a `ComplianceDecision`'s `check_evaluations`
is always the complete audit trail (§16, §19), never a partial one.

Unlike Risk Engine's minimum-across-constraints budget, every check here
is combined by **AND** (§5): a single non-`PASSED` check is sufficient
for BLOCK. `evaluate()` never mutates `risk_decision`, `candidate`,
`score_result`, `account_state`, `market_snapshot`, or `news_state` — all
are read-only, immutable inputs (§2, §19).

The kill switch (§14) and daily lockout (§6) are the only genuinely
stateful facts this engine depends on, and that state lives entirely in
the injected `ComplianceStateStore` — `ComplianceEngine` itself holds no
instance-level decision state, so two engines sharing one store produce
identical decisions for identical inputs (§18 determinism).
"""

from __future__ import annotations

from datetime import timezone
from typing import Optional, Sequence, Tuple

from ..data_pipeline.models import MarketSnapshot
from ..risk_engine.models import RiskDecision
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade
from . import checks as check_fns
from .config import COMPLIANCE_ENGINE_VERSION, DEFAULT_CONFIG, ComplianceEngineConfig
from .logging_sink import (
    log_check_evaluation,
    log_compliance_decision,
    log_daily_lockout_triggered,
    log_kill_switch_triggered,
    log_malformed_request,
)
from .metrics import ComplianceEngineMetrics
from .models import SCHEMA_VERSION, AccountState, CheckStatus, ComplianceDecision, NewsCalendarState, Verdict
from .state_store import ComplianceStateStore

SUPPORTED_RISK_DECISION_SCHEMA_VERSIONS = (1,)


class ComplianceEngine:
    def __init__(
        self,
        state_store: ComplianceStateStore,
        config: ComplianceEngineConfig = DEFAULT_CONFIG,
        metrics: Optional[ComplianceEngineMetrics] = None,
    ):
        self.state_store = state_store
        self.config = config
        self.metrics = metrics

    def evaluate(
        self,
        risk_decision: RiskDecision,
        candidate: CandidateTrade,
        score_result: ScoreResult,
        account_state: Optional[AccountState],
        market_snapshot: Optional[MarketSnapshot],
        news_state: Optional[NewsCalendarState],
        expected_slippage: Optional[float] = None,
    ) -> ComplianceDecision:
        failure_reason = self._validate(risk_decision, candidate, score_result)
        if failure_reason is not None:
            decision = self._malformed_decision(risk_decision, failure_reason)
            log_malformed_request(decision.candidate_id, decision.trace_id, failure_reason)
            log_compliance_decision(decision)
            if self.metrics is not None:
                self.metrics.record_decision(decision)
            return decision

        day = self._trading_day(risk_decision)

        evaluations = []

        killed = self.state_store.is_kill_switch_triggered()
        evaluations.append(check_fns.kill_switch_gate(killed, self.state_store.kill_switch_reason()))

        locked_out = day is not None and self.state_store.is_daily_locked_out(day)
        daily_eval = check_fns.daily_drawdown(account_state, self.config, locked_out)
        evaluations.append(daily_eval)
        if daily_eval.status == CheckStatus.FAILED and not locked_out and day is not None:
            self.state_store.trigger_daily_lockout(
                day, "daily_drawdown_breach", risk_decision.trace_id, risk_decision.timestamp
            )
            log_daily_lockout_triggered(day, "daily_drawdown_breach", risk_decision.trace_id)

        total_eval = check_fns.total_drawdown(account_state, self.config)
        evaluations.append(total_eval)
        if total_eval.status == CheckStatus.FAILED and not killed:
            self.state_store.trigger_kill_switch(
                "total_drawdown_breach", risk_decision.trace_id, risk_decision.timestamp
            )
            log_kill_switch_triggered("total_drawdown_breach", risk_decision.trace_id)

        evaluations.append(
            check_fns.news_restriction(news_state, risk_decision.symbol, risk_decision.timestamp)
        )
        evaluations.append(check_fns.session_restriction(self.config, risk_decision.timestamp))
        evaluations.append(
            check_fns.weekend_restriction(
                market_snapshot.market_status if market_snapshot is not None else None
            )
        )
        evaluations.append(
            check_fns.spread_validation(
                market_snapshot.spread if market_snapshot is not None else None,
                risk_decision.symbol,
                self.config,
            )
        )
        evaluations.append(
            check_fns.slippage_validation(expected_slippage, risk_decision.symbol, self.config)
        )
        evaluations.append(
            check_fns.max_positions(
                account_state, risk_decision.symbol, risk_decision.direction, self.config
            )
        )

        evaluations = tuple(evaluations)
        for evaluation in evaluations:
            log_check_evaluation(risk_decision.candidate_id, risk_decision.trace_id, evaluation)

        blocking_rules = tuple(sorted(e.check for e in evaluations if e.blocks))
        verdict = Verdict.BLOCK if blocking_rules else Verdict.APPROVE
        reason_codes = blocking_rules if blocking_rules else tuple(sorted(e.check for e in evaluations))

        decision = ComplianceDecision(
            schema_version=SCHEMA_VERSION,
            trace_id=risk_decision.trace_id,
            candidate_id=risk_decision.candidate_id,
            strategy_id=risk_decision.strategy_id,
            symbol=risk_decision.symbol,
            timeframe=risk_decision.timeframe,
            timestamp=risk_decision.timestamp,
            direction=risk_decision.direction,
            verdict=verdict,
            blocking_rules=blocking_rules,
            reason_codes=reason_codes,
            check_evaluations=evaluations,
            compliance_engine_version=COMPLIANCE_ENGINE_VERSION,
        )
        log_compliance_decision(decision)
        if self.metrics is not None:
            self.metrics.record_decision(decision)
            self.metrics.set_kill_switch_active(self.state_store.is_kill_switch_triggered())
            self.metrics.set_daily_lockout_active(day is not None and self.state_store.is_daily_locked_out(day))
        return decision

    def evaluate_batch(
        self,
        requests: Sequence[
            Tuple[
                RiskDecision,
                CandidateTrade,
                ScoreResult,
                Optional[AccountState],
                Optional[MarketSnapshot],
                Optional[NewsCalendarState],
                Optional[float],
            ]
        ],
    ) -> Tuple[ComplianceDecision, ...]:
        return tuple(self.evaluate(*request) for request in requests)

    def _validate(
        self, risk_decision: RiskDecision, candidate: CandidateTrade, score_result: ScoreResult
    ) -> Optional[str]:
        if risk_decision.schema_version not in SUPPORTED_RISK_DECISION_SCHEMA_VERSIONS:
            return "unsupported_schema_version"
        if not risk_decision.candidate_id or not risk_decision.trace_id or not risk_decision.symbol:
            return "malformed_risk_decision"
        if (
            candidate.trace_id != risk_decision.trace_id
            or candidate.candidate_id != risk_decision.candidate_id
        ):
            return "candidate_mismatch"
        if (
            score_result.trace_id != risk_decision.trace_id
            or score_result.candidate_id != risk_decision.candidate_id
        ):
            return "score_result_mismatch"
        return None

    def _trading_day(self, risk_decision: RiskDecision) -> Optional[str]:
        if risk_decision.timestamp.tzinfo is None:
            return None
        return risk_decision.timestamp.astimezone(timezone.utc).date().isoformat()

    def _malformed_decision(self, risk_decision: RiskDecision, reason: str) -> ComplianceDecision:
        return ComplianceDecision(
            schema_version=SCHEMA_VERSION,
            trace_id=risk_decision.trace_id,
            candidate_id=risk_decision.candidate_id,
            strategy_id=risk_decision.strategy_id,
            symbol=risk_decision.symbol,
            timeframe=risk_decision.timeframe,
            timestamp=risk_decision.timestamp,
            direction=risk_decision.direction,
            verdict=Verdict.BLOCK,
            blocking_rules=(reason,),
            reason_codes=(reason,),
            check_evaluations=(),
            compliance_engine_version=COMPLIANCE_ENGINE_VERSION,
        )
