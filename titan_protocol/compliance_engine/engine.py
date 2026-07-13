"""`ComplianceEngine` -- the Prop Firm Compliance Engine's orchestrator
(Phase 2E). The final authority before execution.

Consumes `EvidenceSnapshot` (ADR-024), `MarketIntelligenceSnapshot`
(ADR-025), `StrategySnapshot` (ADR-026), `RiskSnapshot` and
`PortfolioState` (ADR-027), and `AccountState` (this ADR) for one pair,
and produces a `ComplianceSnapshot`. May only APPROVE, REDUCE, or
REJECT -- never increase risk (ADR-028 Hard Rule 1).

Thread safety: `ComplianceEngine` holds **no mutable state at all** --
every `evaluate()` call is a pure function of its six inputs plus
`now` (ADR-028 §3, Hard Rule 6). Compliance-lock/emergency-stop
persistence is entirely the caller's responsibility, via
`AccountState` and this call's `lock_recommendation` output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from titan_protocol.evidence_engine.models import EvidenceSnapshot
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot
from titan_protocol.risk_engine.models import PortfolioState, RiskSnapshot
from titan_protocol.strategy_engine.models import StrategySnapshot

from .bands import BandEvaluation
from .compliance_score import compute_compliance_score
from .config import ComplianceEngineConfig
from .consecutive_loss import consecutive_loss_pause_triggered
from .daily_loss import evaluate_daily_loss_protection
from .drawdown import evaluate_drawdown_protection
from .explainability import build_compliance_snapshot
from .logging_sink import log_compliance_snapshot
from .market_conditions import check_max_spread, check_market_safety, check_news_blackout, check_peg_policy, check_session_restriction
from .metrics import ComplianceEngineMetrics
from .models import AccountState, ComplianceDecision, ComplianceRuleId, ComplianceSnapshot, LockRecommendation
from .position_limits import check_position_limits
from .profit_protection import evaluate_profit_protection
from .rule_profile import (
    check_consistency_rule,
    check_max_trades_per_day,
    check_pair_disabled,
    check_required_stop_loss,
    check_weekend_restriction,
)


class ComplianceEngine:
    def __init__(self, config: ComplianceEngineConfig, metrics: Optional[ComplianceEngineMetrics] = None) -> None:
        self.config = config
        self.metrics = metrics

    def _reject(
        self, pair: str, now: datetime, original_size_r: float, rule: ComplianceRuleId, reason: str,
        account: AccountState, profile, lock_recommendation: Optional[LockRecommendation] = None,
    ) -> ComplianceSnapshot:
        compliance_score = compute_compliance_score(account, profile, self.config)
        snapshot = build_compliance_snapshot(
            pair=pair, now=now, decision=ComplianceDecision.REJECT,
            original_size_r=original_size_r, approved_size_r=0.0, reason=reason,
            triggered_rules=(rule,), warnings=(), compliance_score=compliance_score,
            lock_recommendation=lock_recommendation,
        )
        log_compliance_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            self.metrics.record_rejection()
        return snapshot

    def evaluate(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        strategy: StrategySnapshot,
        risk: RiskSnapshot,
        portfolio_state: PortfolioState,
        account_state: AccountState,
        now: Optional[datetime] = None,
    ) -> ComplianceSnapshot:
        if evidence.report.symbol != pair:
            raise ValueError(f"evidence.report.symbol ({evidence.report.symbol!r}) does not match pair ({pair!r})")
        if market_intelligence.pair != pair:
            raise ValueError(f"market_intelligence.pair ({market_intelligence.pair!r}) does not match pair ({pair!r})")
        if strategy.pair != pair:
            raise ValueError(f"strategy.pair ({strategy.pair!r}) does not match pair ({pair!r})")
        if risk.pair != pair:
            raise ValueError(f"risk.pair ({risk.pair!r}) does not match pair ({pair!r})")
        now = now or risk.generated_at or datetime.now(timezone.utc)

        profile = self.config.profile_for(account_state.rule_profile_name)
        original_size_r = risk.approved_risk_r if risk.approved else 0.0

        # 1. Emergency/lock/upstream-authority gates -- fixed order, deterministic.
        if account_state.emergency_stop_active:
            return self._reject(pair, now, original_size_r, ComplianceRuleId.EMERGENCY_STOP_ACTIVE, "Emergency stop is active.", account_state, profile)
        if account_state.compliance_lock.active:
            return self._reject(pair, now, original_size_r, ComplianceRuleId.COMPLIANCE_LOCK_ACTIVE, f"Compliance lock active: {account_state.compliance_lock.reason}", account_state, profile)
        if not risk.approved:
            return self._reject(pair, now, original_size_r, ComplianceRuleId.RISK_NOT_APPROVED, "Risk Engine did not approve this trade.", account_state, profile)
        if strategy.rejected or strategy.winning_strategy is None:
            return self._reject(pair, now, original_size_r, ComplianceRuleId.NO_QUALIFIED_STRATEGY, "No qualified strategy.", account_state, profile)

        # 2. Market-condition gates -- never queries a provider directly, reads MarketIntelligenceSnapshot only.
        market_safety_violation = check_market_safety(market_intelligence)
        if market_safety_violation is not None:
            return self._reject(pair, now, original_size_r, market_safety_violation, f"{market_safety_violation.value} (market safety).", account_state, profile)
        if check_pair_disabled(pair, self.config):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.PAIR_DISABLED, f"{pair} is disabled.", account_state, profile)
        if check_session_restriction(evidence, profile):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.SESSION_NOT_APPROVED, f"Session {evidence.session.session.value} is not approved.", account_state, profile)
        if check_news_blackout(market_intelligence, profile):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.NEWS_BLACKOUT, "News blackout active.", account_state, profile)
        if check_peg_policy(market_intelligence):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.PEG_POLICY_ACTIVE, "Peg/policy event active.", account_state, profile)
        if check_max_spread(market_intelligence, profile):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.SPREAD_TOO_HIGH, "Spread exceeds the configured maximum.", account_state, profile)
        if check_weekend_restriction(now, profile, self.config):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.WEEKEND_RESTRICTION, "Weekend holding restriction in effect.", account_state, profile)
        if check_required_stop_loss(risk, profile):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.STOP_LOSS_MISSING, "No stop-loss-defined sizing available.", account_state, profile)

        # 3. Operational/behavioral gates.
        if check_max_trades_per_day(account_state, profile):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.MAX_TRADES_PER_DAY_EXCEEDED, "Maximum trades per day reached.", account_state, profile)
        if check_consistency_rule(account_state, profile):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.CONSISTENCY_RULE_VIOLATED, "Single-day profit share exceeds the configured consistency limit.", account_state, profile)
        if consecutive_loss_pause_triggered(account_state, self.config):
            return self._reject(pair, now, original_size_r, ComplianceRuleId.CONSECUTIVE_LOSS_PAUSE, "Consecutive loss threshold reached -- entries paused.", account_state, profile)

        position_violation, _exposure = check_position_limits(pair, original_size_r, portfolio_state, account_state, profile)
        if position_violation is not None:
            return self._reject(pair, now, original_size_r, position_violation, f"{position_violation.value}.", account_state, profile)

        # 4. Graduated risk-reduction curves (ADR-028 §5.1-5.3).
        evidence_score = evidence.report.score.composite
        strategy_score = strategy.winning_strategy.qualification.score

        daily_eval = evaluate_daily_loss_protection(account_state, profile, self.config, evidence_score, strategy_score)
        if daily_eval.hard_reject:
            rule = (
                ComplianceRuleId.INSUFFICIENT_CONFIDENCE_FOR_ELEVATED_LOSS_BAND if daily_eval.gate_kind == "evidence"
                else ComplianceRuleId.INSUFFICIENT_QUALITY_FOR_ELEVATED_LOSS_BAND if daily_eval.gate_kind == "strategy"
                else ComplianceRuleId.DAILY_LOSS_LIMIT_EXCEEDED
            )
            reason = daily_eval.gate_failed_reason or f"Daily loss protection band {daily_eval.label!r} rejects all new positions."
            lock_recommendation = None if daily_eval.gate_failed_reason else LockRecommendation(trigger=True, reason="daily loss limit reached")
            return self._reject(pair, now, original_size_r, rule, reason, account_state, profile, lock_recommendation)

        drawdown_eval = evaluate_drawdown_protection(account_state, profile, self.config)
        if drawdown_eval.hard_reject:
            return self._reject(
                pair, now, original_size_r, ComplianceRuleId.TOTAL_DRAWDOWN_EXCEEDED,
                f"Total drawdown protection band {drawdown_eval.label!r} rejects all new positions.",
                account_state, profile, LockRecommendation(trigger=True, reason="total drawdown limit reached"),
            )

        profit_eval: Optional[BandEvaluation] = evaluate_profit_protection(account_state, self.config)
        if profit_eval is not None and profit_eval.hard_reject:
            return self._reject(
                pair, now, original_size_r, ComplianceRuleId.PROFIT_PROTECTION_STOP,
                profit_eval.gate_failed_reason or "Daily profit protection stop threshold reached.",
                account_state, profile,
            )

        multipliers = [daily_eval.multiplier, drawdown_eval.multiplier]
        triggered = []
        if daily_eval.multiplier < 1.0:
            triggered.append(ComplianceRuleId.DAILY_LOSS_REDUCTION)
        if drawdown_eval.multiplier < 1.0:
            triggered.append(ComplianceRuleId.DRAWDOWN_REDUCTION)
        if profit_eval is not None:
            multipliers.append(profit_eval.multiplier)
            if profit_eval.multiplier < 1.0:
                triggered.append(ComplianceRuleId.PROFIT_PROTECTION_REDUCTION)

        final_multiplier = min(multipliers) if multipliers else 1.0
        approved_size_r = original_size_r * final_multiplier
        decision = ComplianceDecision.APPROVE if final_multiplier >= 1.0 else ComplianceDecision.REDUCE

        if decision is ComplianceDecision.APPROVE:
            reason = "Approved -- within all configured compliance limits."
        else:
            reason = f"Reduced to {final_multiplier * 100:.0f}% of Risk Engine's recommendation ({', '.join(r.value for r in triggered)})."

        compliance_score = compute_compliance_score(account_state, profile, self.config)
        snapshot = build_compliance_snapshot(
            pair=pair, now=now, decision=decision, original_size_r=original_size_r,
            approved_size_r=approved_size_r, reason=reason, triggered_rules=tuple(triggered),
            warnings=(), compliance_score=compliance_score, lock_recommendation=None,
        )
        log_compliance_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            if decision is ComplianceDecision.APPROVE:
                self.metrics.record_approval()
            else:
                self.metrics.record_reduction()
        return snapshot

    def evaluate_batch(
        self,
        pairs: Dict[str, Tuple[EvidenceSnapshot, MarketIntelligenceSnapshot, StrategySnapshot, RiskSnapshot]],
        portfolio_state: PortfolioState,
        account_state: AccountState,
        now: Optional[datetime] = None,
    ) -> Tuple[ComplianceSnapshot, ...]:
        """Evaluates every pair, sorted by symbol for determinism.
        `pairs[pair]` is `(evidence_snapshot, market_intelligence_snapshot, strategy_snapshot, risk_snapshot)`."""

        results = tuple(
            self.evaluate(pair, evidence, market_intelligence, strategy, risk, portfolio_state, account_state, now)
            for pair, (evidence, market_intelligence, strategy, risk) in sorted(pairs.items())
        )
        if self.metrics is not None:
            self.metrics.record_batch_evaluation()
        return results


__all__ = ["ComplianceEngine"]
