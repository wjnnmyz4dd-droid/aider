"""Per-check pure evaluation functions (ADR-007 §6, plus the task's
explicitly requested SL/TP/RR/sizing/position-freshness checks — see
`engine.py`'s module docstring for how each maps onto ADR-007 §6's text).

Every function here is a pure function of its explicit arguments — none
reads a clock, a database, or any other I/O (that responsibility belongs
to `idempotency_store.py` and `engine.py`, which read the store/clock
once and pass plain values in here). This mirrors
`compliance_engine.checks`'s discipline: each check is independent,
side-effect free, and combined by the caller by AND (ADR-007 §6).

Every check resolves to `CheckStatus.UNEVALUABLE` (which blocks, exactly
like `FAILED`) whenever a required input is missing — never a default
`PASSED` (ADR-007 §8 Hard Rule).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..compliance_engine.models import ComplianceDecision
from ..data_pipeline.models import MarketSnapshot
from ..risk_engine.models import RiskDecision
from ..scanner.models import Direction
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade
from .config import ExecutionValidatorConfig
from .models import AccountState, BrokerState, CheckEvaluation, CheckStatus


def compliance_approval_valid(compliance_decision: Optional[ComplianceDecision]) -> CheckEvaluation:
    if compliance_decision is None:
        return CheckEvaluation(
            "COMPLIANCE_APPROVAL_VALID", CheckStatus.UNEVALUABLE, "missing compliance decision"
        )
    if compliance_decision.verdict.value != "APPROVE":
        return CheckEvaluation(
            "COMPLIANCE_APPROVAL_VALID",
            CheckStatus.FAILED,
            f"compliance verdict is {compliance_decision.verdict.value}, not APPROVE",
        )
    return CheckEvaluation("COMPLIANCE_APPROVAL_VALID", CheckStatus.PASSED, "compliance verdict is APPROVE")


SUPPORTED_RISK_DECISION_SCHEMA_VERSIONS = (1,)


def risk_decision_consistent(
    risk_decision: Optional[RiskDecision], compliance_decision: Optional[ComplianceDecision]
) -> CheckEvaluation:
    if risk_decision is None:
        return CheckEvaluation("RISK_DECISION_CONSISTENT", CheckStatus.UNEVALUABLE, "missing risk decision")
    if compliance_decision is None:
        return CheckEvaluation(
            "RISK_DECISION_CONSISTENT", CheckStatus.UNEVALUABLE, "missing compliance decision for cross-check"
        )
    if risk_decision.schema_version not in SUPPORTED_RISK_DECISION_SCHEMA_VERSIONS:
        return CheckEvaluation("RISK_DECISION_CONSISTENT", CheckStatus.FAILED, "unsupported schema version")
    if (
        risk_decision.trace_id != compliance_decision.trace_id
        or risk_decision.candidate_id != compliance_decision.candidate_id
    ):
        return CheckEvaluation(
            "RISK_DECISION_CONSISTENT", CheckStatus.FAILED, "trace_id/candidate_id mismatch vs compliance decision"
        )
    return CheckEvaluation("RISK_DECISION_CONSISTENT", CheckStatus.PASSED, "consistent with compliance decision")


def candidate_integrity(
    candidate: CandidateTrade, score_result: ScoreResult, risk_decision: Optional[RiskDecision]
) -> CheckEvaluation:
    if risk_decision is None:
        return CheckEvaluation("CANDIDATE_INTEGRITY", CheckStatus.UNEVALUABLE, "missing risk decision for cross-check")
    if not candidate.trace_id or not candidate.candidate_id:
        return CheckEvaluation("CANDIDATE_INTEGRITY", CheckStatus.FAILED, "malformed candidate: empty trace_id/candidate_id")
    ids = {
        (candidate.trace_id, candidate.candidate_id),
        (score_result.trace_id, score_result.candidate_id),
        (risk_decision.trace_id, risk_decision.candidate_id),
    }
    if len(ids) != 1:
        return CheckEvaluation(
            "CANDIDATE_INTEGRITY", CheckStatus.FAILED, "trace_id/candidate_id mismatch across candidate/score_result/risk decision"
        )
    return CheckEvaluation("CANDIDATE_INTEGRITY", CheckStatus.PASSED, "candidate identity consistent")


def trade_not_stale(
    risk_decision: Optional[RiskDecision], now: datetime, config: ExecutionValidatorConfig
) -> CheckEvaluation:
    if risk_decision is None:
        return CheckEvaluation("TRADE_NOT_STALE", CheckStatus.UNEVALUABLE, "missing risk decision")
    if now.tzinfo is None or risk_decision.timestamp.tzinfo is None:
        return CheckEvaluation("TRADE_NOT_STALE", CheckStatus.UNEVALUABLE, "timestamp is not timezone-aware")
    age = (now - risk_decision.timestamp).total_seconds()
    if age < 0:
        return CheckEvaluation("TRADE_NOT_STALE", CheckStatus.UNEVALUABLE, "decision timestamp is in the future (clock skew)")
    if age > config.max_order_age_seconds:
        return CheckEvaluation(
            "TRADE_NOT_STALE", CheckStatus.FAILED, f"age={age:.3f}s > max_order_age_seconds={config.max_order_age_seconds}s"
        )
    return CheckEvaluation("TRADE_NOT_STALE", CheckStatus.PASSED, f"age={age:.3f}s within max_order_age_seconds")


def market_open(market_snapshot: Optional[MarketSnapshot]) -> CheckEvaluation:
    if market_snapshot is None or market_snapshot.market_status is None:
        return CheckEvaluation("MARKET_OPEN", CheckStatus.UNEVALUABLE, "missing fresh market snapshot")
    if market_snapshot.market_status.upper() != "OPEN":
        return CheckEvaluation("MARKET_OPEN", CheckStatus.FAILED, f"market_status={market_snapshot.market_status}")
    return CheckEvaluation("MARKET_OPEN", CheckStatus.PASSED, "market is open")


def symbol_tradable(broker_state: Optional[BrokerState]) -> CheckEvaluation:
    if broker_state is None or broker_state.symbol_tradable is None:
        return CheckEvaluation("SYMBOL_TRADABLE", CheckStatus.UNEVALUABLE, "missing fresh broker state")
    if not broker_state.symbol_tradable:
        return CheckEvaluation("SYMBOL_TRADABLE", CheckStatus.FAILED, "symbol is not currently tradable")
    return CheckEvaluation("SYMBOL_TRADABLE", CheckStatus.PASSED, "symbol is tradable")


def price_valid(market_snapshot: Optional[MarketSnapshot]) -> CheckEvaluation:
    if market_snapshot is None or market_snapshot.price is None:
        return CheckEvaluation("PRICE_VALID", CheckStatus.UNEVALUABLE, "missing fresh price")
    if market_snapshot.price <= 0:
        return CheckEvaluation("PRICE_VALID", CheckStatus.FAILED, f"price={market_snapshot.price} is not positive")
    return CheckEvaluation("PRICE_VALID", CheckStatus.PASSED, f"price={market_snapshot.price}")


def spread_unchanged(
    market_snapshot: Optional[MarketSnapshot], symbol: str, config: ExecutionValidatorConfig
) -> CheckEvaluation:
    if market_snapshot is None or market_snapshot.spread is None:
        return CheckEvaluation("SPREAD_UNCHANGED", CheckStatus.UNEVALUABLE, "missing fresh spread")
    threshold = config.max_spread_for(symbol)
    if threshold is None:
        return CheckEvaluation("SPREAD_UNCHANGED", CheckStatus.UNEVALUABLE, f"no spread threshold configured for {symbol}")
    spread = market_snapshot.spread
    if spread > threshold:
        return CheckEvaluation("SPREAD_UNCHANGED", CheckStatus.FAILED, f"spread={spread} > {threshold}")
    warning = None
    if spread >= threshold * config.warning_threshold_ratio:
        warning = f"SPREAD_UNCHANGED: spread={spread} is within {config.warning_threshold_ratio:.0%} of threshold {threshold}"
    return CheckEvaluation("SPREAD_UNCHANGED", CheckStatus.PASSED, f"spread={spread} <= {threshold}", warning=warning)


def slippage_within_limits(
    market_snapshot: Optional[MarketSnapshot], reference_price: Optional[float], config: ExecutionValidatorConfig
) -> CheckEvaluation:
    if market_snapshot is None or market_snapshot.price is None:
        return CheckEvaluation("SLIPPAGE_WITHIN_LIMITS", CheckStatus.UNEVALUABLE, "missing fresh price")
    if reference_price is None:
        return CheckEvaluation(
            "SLIPPAGE_WITHIN_LIMITS", CheckStatus.UNEVALUABLE, "missing reference price from decision time"
        )
    drift = abs(market_snapshot.price - reference_price)
    if drift > config.max_price_drift:
        return CheckEvaluation(
            "SLIPPAGE_WITHIN_LIMITS", CheckStatus.FAILED, f"drift={drift} > max_price_drift={config.max_price_drift}"
        )
    warning = None
    if drift >= config.max_price_drift * config.warning_threshold_ratio:
        warning = (
            f"SLIPPAGE_WITHIN_LIMITS: drift={drift} is within {config.warning_threshold_ratio:.0%} "
            f"of max_price_drift={config.max_price_drift}"
        )
    return CheckEvaluation(
        "SLIPPAGE_WITHIN_LIMITS", CheckStatus.PASSED, f"drift={drift} <= {config.max_price_drift}", warning=warning
    )


def order_synchronized(
    candidate: CandidateTrade,
    risk_decision: Optional[RiskDecision],
    compliance_decision: Optional[ComplianceDecision],
) -> CheckEvaluation:
    if risk_decision is None or compliance_decision is None:
        return CheckEvaluation("ORDER_SYNCHRONIZED", CheckStatus.UNEVALUABLE, "missing risk or compliance decision")
    if not (candidate.direction == risk_decision.direction == compliance_decision.direction):
        return CheckEvaluation("ORDER_SYNCHRONIZED", CheckStatus.FAILED, "direction mismatch across candidate/risk/compliance")
    if not (candidate.symbol == risk_decision.symbol == compliance_decision.symbol):
        return CheckEvaluation("ORDER_SYNCHRONIZED", CheckStatus.FAILED, "symbol mismatch across candidate/risk/compliance")
    return CheckEvaluation("ORDER_SYNCHRONIZED", CheckStatus.PASSED, "order parameters synchronized")


def account_synchronized(
    risk_decision: Optional[RiskDecision], account_state: Optional[AccountState], config: ExecutionValidatorConfig
) -> CheckEvaluation:
    if risk_decision is None:
        return CheckEvaluation("ACCOUNT_SYNCHRONIZED", CheckStatus.UNEVALUABLE, "missing risk decision")
    if account_state is None or account_state.equity is None:
        return CheckEvaluation("ACCOUNT_SYNCHRONIZED", CheckStatus.UNEVALUABLE, "missing fresh account equity")
    expected_amount = account_state.equity * risk_decision.approved_risk_percent / 100.0
    approved_amount = risk_decision.approved_risk_amount
    tolerance = config.account_drift_tolerance_ratio * max(abs(approved_amount), 1e-9)
    if abs(expected_amount - approved_amount) > tolerance:
        return CheckEvaluation(
            "ACCOUNT_SYNCHRONIZED",
            CheckStatus.FAILED,
            f"fresh equity implies amount={expected_amount:.2f}, decision assumed {approved_amount:.2f}",
        )
    return CheckEvaluation("ACCOUNT_SYNCHRONIZED", CheckStatus.PASSED, "fresh account state consistent with decision")


def sufficient_margin(
    risk_decision: Optional[RiskDecision], account_state: Optional[AccountState]
) -> CheckEvaluation:
    if risk_decision is None:
        return CheckEvaluation("SUFFICIENT_MARGIN", CheckStatus.UNEVALUABLE, "missing risk decision")
    if account_state is None or account_state.available_margin is None:
        return CheckEvaluation("SUFFICIENT_MARGIN", CheckStatus.UNEVALUABLE, "missing fresh available margin")
    if account_state.available_margin < risk_decision.approved_risk_amount:
        return CheckEvaluation(
            "SUFFICIENT_MARGIN",
            CheckStatus.FAILED,
            f"available_margin={account_state.available_margin} < required={risk_decision.approved_risk_amount}",
        )
    return CheckEvaluation("SUFFICIENT_MARGIN", CheckStatus.PASSED, "sufficient margin available")


def broker_connection_healthy(broker_state: Optional[BrokerState]) -> CheckEvaluation:
    if broker_state is None:
        return CheckEvaluation("BROKER_CONNECTION_HEALTHY", CheckStatus.UNEVALUABLE, "missing fresh broker state")
    if not broker_state.connected:
        return CheckEvaluation("BROKER_CONNECTION_HEALTHY", CheckStatus.FAILED, "broker connection is not healthy")
    return CheckEvaluation("BROKER_CONNECTION_HEALTHY", CheckStatus.PASSED, "broker connection healthy")


def no_duplicate_request(candidate: CandidateTrade, already_seen: bool) -> CheckEvaluation:
    if not candidate.candidate_id:
        return CheckEvaluation("NO_DUPLICATE_REQUEST", CheckStatus.UNEVALUABLE, "missing candidate_id")
    if already_seen:
        return CheckEvaluation(
            "NO_DUPLICATE_REQUEST", CheckStatus.FAILED, f"candidate_id={candidate.candidate_id} already processed"
        )
    return CheckEvaluation("NO_DUPLICATE_REQUEST", CheckStatus.PASSED, "first submission attempt for this candidate")


def _correct_side(direction: Direction, price: float, level: float, is_stop_loss: bool) -> Optional[bool]:
    if direction == Direction.UP:
        return level < price if is_stop_loss else level > price
    if direction == Direction.DOWN:
        return level > price if is_stop_loss else level < price
    return None


def stop_loss_valid(
    direction: Direction, market_snapshot: Optional[MarketSnapshot], intended_stop_loss: Optional[float]
) -> CheckEvaluation:
    if intended_stop_loss is None:
        return CheckEvaluation("STOP_LOSS_VALID", CheckStatus.UNEVALUABLE, "no intended stop-loss supplied")
    if market_snapshot is None or market_snapshot.price is None:
        return CheckEvaluation("STOP_LOSS_VALID", CheckStatus.UNEVALUABLE, "missing fresh price")
    correct_side = _correct_side(direction, market_snapshot.price, intended_stop_loss, is_stop_loss=True)
    if correct_side is None:
        return CheckEvaluation("STOP_LOSS_VALID", CheckStatus.UNEVALUABLE, f"cannot validate stop-loss side for direction={direction.value}")
    if not correct_side:
        return CheckEvaluation("STOP_LOSS_VALID", CheckStatus.FAILED, f"stop_loss={intended_stop_loss} is on the wrong side of price={market_snapshot.price}")
    return CheckEvaluation("STOP_LOSS_VALID", CheckStatus.PASSED, "stop-loss present and on the correct side")


def take_profit_valid(
    direction: Direction, market_snapshot: Optional[MarketSnapshot], intended_take_profit: Optional[float]
) -> CheckEvaluation:
    if intended_take_profit is None:
        return CheckEvaluation("TAKE_PROFIT_VALID", CheckStatus.UNEVALUABLE, "no intended take-profit supplied")
    if market_snapshot is None or market_snapshot.price is None:
        return CheckEvaluation("TAKE_PROFIT_VALID", CheckStatus.UNEVALUABLE, "missing fresh price")
    correct_side = _correct_side(direction, market_snapshot.price, intended_take_profit, is_stop_loss=False)
    if correct_side is None:
        return CheckEvaluation("TAKE_PROFIT_VALID", CheckStatus.UNEVALUABLE, f"cannot validate take-profit side for direction={direction.value}")
    if not correct_side:
        return CheckEvaluation("TAKE_PROFIT_VALID", CheckStatus.FAILED, f"take_profit={intended_take_profit} is on the wrong side of price={market_snapshot.price}")
    return CheckEvaluation("TAKE_PROFIT_VALID", CheckStatus.PASSED, "take-profit present and on the correct side")


def minimum_rr(
    direction: Direction,
    market_snapshot: Optional[MarketSnapshot],
    intended_stop_loss: Optional[float],
    intended_take_profit: Optional[float],
    config: ExecutionValidatorConfig,
) -> CheckEvaluation:
    if intended_stop_loss is None or intended_take_profit is None:
        return CheckEvaluation("MINIMUM_RR", CheckStatus.UNEVALUABLE, "missing intended stop-loss/take-profit")
    if market_snapshot is None or market_snapshot.price is None:
        return CheckEvaluation("MINIMUM_RR", CheckStatus.UNEVALUABLE, "missing fresh price")
    price = market_snapshot.price
    risk = abs(price - intended_stop_loss)
    if risk <= 0:
        return CheckEvaluation("MINIMUM_RR", CheckStatus.UNEVALUABLE, "zero-risk stop-loss distance")
    reward = abs(intended_take_profit - price)
    rr = reward / risk
    if rr < config.min_risk_reward_ratio:
        return CheckEvaluation("MINIMUM_RR", CheckStatus.FAILED, f"rr={rr:.2f} < min_risk_reward_ratio={config.min_risk_reward_ratio}")
    return CheckEvaluation("MINIMUM_RR", CheckStatus.PASSED, f"rr={rr:.2f} >= {config.min_risk_reward_ratio}")


def position_sizing_valid(risk_decision: Optional[RiskDecision]) -> CheckEvaluation:
    if risk_decision is None:
        return CheckEvaluation("POSITION_SIZING_VALID", CheckStatus.UNEVALUABLE, "missing risk decision")
    if risk_decision.approved_risk_percent <= 0 or risk_decision.approved_risk_amount <= 0:
        return CheckEvaluation("POSITION_SIZING_VALID", CheckStatus.FAILED, "zero or negative approved risk percent/amount")
    if risk_decision.lot_size is not None and risk_decision.lot_size <= 0:
        return CheckEvaluation("POSITION_SIZING_VALID", CheckStatus.FAILED, "non-positive lot_size")
    return CheckEvaluation("POSITION_SIZING_VALID", CheckStatus.PASSED, "position sizing values are valid")


def existing_position_validation(account_state: Optional[AccountState]) -> CheckEvaluation:
    """A freshness gate, not a new position-count business rule — count
    limits are already Compliance Engine's owned authority (`ADR-006`
    §13); this only confirms a fresh account/position read was obtained
    for this evaluation (ADR-007 §2's "read fresh" requirement)."""
    if account_state is None:
        return CheckEvaluation("EXISTING_POSITION_VALIDATION", CheckStatus.UNEVALUABLE, "missing fresh account/position state")
    return CheckEvaluation("EXISTING_POSITION_VALIDATION", CheckStatus.PASSED, "fresh account/position state available")
