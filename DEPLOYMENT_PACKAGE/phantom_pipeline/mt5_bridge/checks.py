"""Pure validation and translation functions (ADR-008 §1, §2, §4, §7).

Every function here is a pure function of its explicit arguments — no
I/O, no clock reads beyond an explicit `now`/`timestamp` parameter, no
broker calls (that responsibility belongs to `broker_adapter.py`, called
only from `engine.py`). Translation functions perform a direct field
mapping only — never a re-derivation of sizing, SL/TP, scores, risk, or
compliance (ADR-008 Hard Rules).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..compliance_engine.models import ComplianceDecision
from ..execution_validator.models import ExecutionDecision, Verdict
from ..risk_engine.models import RiskDecision
from ..strategy_engine.models import CandidateTrade
from .models import BrokerRequest, PositionAdjustmentRequest, PositionCloseRequest, RequestKind, SCHEMA_VERSION


def validate_execution_decision(execution_decision: Optional[ExecutionDecision]) -> Optional[str]:
    """ADR-008 Hard Rules: "Accept only `ExecutionDecision` APPROVE."
    Every request lacking a matching APPROVE is rejected before any
    broker communication is attempted."""
    if execution_decision is None:
        return "missing_execution_decision"
    if execution_decision.verdict != Verdict.APPROVE:
        return "execution_decision_not_approved"
    return None


def validate_order_consistency(
    candidate: CandidateTrade,
    risk_decision: Optional[RiskDecision],
    compliance_decision: Optional[ComplianceDecision],
    execution_decision: ExecutionDecision,
) -> Optional[str]:
    if risk_decision is None:
        return "missing_risk_decision"
    if compliance_decision is None:
        return "missing_compliance_decision"
    ids = {
        (candidate.trace_id, candidate.candidate_id),
        (risk_decision.trace_id, risk_decision.candidate_id),
        (compliance_decision.trace_id, compliance_decision.candidate_id),
        (execution_decision.trace_id, execution_decision.candidate_id),
    }
    if len(ids) != 1:
        return "trace_id_candidate_id_mismatch"
    return None


def validate_sizing(risk_decision: RiskDecision) -> Optional[str]:
    if risk_decision.lot_size is None:
        return "missing_lot_size"
    if risk_decision.lot_size <= 0:
        return "invalid_lot_size"
    return None


def validate_position_adjustment(request: Optional[PositionAdjustmentRequest]) -> Optional[str]:
    if request is None:
        return "missing_position_adjustment_request"
    if not request.position_id:
        return "missing_position_id"
    if request.new_stop_loss is None and request.new_take_profit is None:
        return "no_adjustment_specified"
    return None


def validate_position_close(request: Optional[PositionCloseRequest]) -> Optional[str]:
    if request is None:
        return "missing_position_close_request"
    if not request.position_id:
        return "missing_position_id"
    if request.close_fraction is None or not (0.0 < request.close_fraction <= 1.0):
        return "invalid_close_fraction"
    return None


def translate_order(
    execution_decision: ExecutionDecision,
    risk_decision: RiskDecision,
    candidate: CandidateTrade,
    execution_id: str,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    now: datetime,
) -> BrokerRequest:
    """A direct field mapping from already-decided upstream objects —
    never a re-derivation (ADR-008 Hard Rules, §2)."""
    return BrokerRequest(
        schema_version=SCHEMA_VERSION,
        execution_id=execution_id,
        trace_id=execution_decision.trace_id,
        request_kind=RequestKind.OPEN,
        symbol=risk_decision.symbol,
        direction=candidate.direction,
        lot_size=risk_decision.lot_size,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_id=None,
        close_fraction=None,
        candidate_id=execution_decision.candidate_id,
        timestamp=now,
    )


def translate_position_adjustment(request: PositionAdjustmentRequest, now: datetime) -> BrokerRequest:
    """A direct field mapping from `PositionAdjustmentRequest` — never a
    re-derivation (ADR-008 Amendment 1)."""
    return BrokerRequest(
        schema_version=SCHEMA_VERSION,
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        request_kind=RequestKind.ADJUST,
        symbol=None,
        direction=None,
        lot_size=None,
        stop_loss=request.new_stop_loss,
        take_profit=request.new_take_profit,
        position_id=request.position_id,
        close_fraction=None,
        candidate_id=None,
        timestamp=now,
    )


def translate_position_close(request: PositionCloseRequest, now: datetime) -> BrokerRequest:
    """A direct field mapping from `PositionCloseRequest` — never a
    re-derivation (ADR-008 Amendment 1)."""
    return BrokerRequest(
        schema_version=SCHEMA_VERSION,
        execution_id=request.execution_id,
        trace_id=request.trace_id,
        request_kind=RequestKind.CLOSE,
        symbol=None,
        direction=None,
        lot_size=None,
        stop_loss=None,
        take_profit=None,
        position_id=request.position_id,
        close_fraction=request.close_fraction,
        candidate_id=None,
        timestamp=now,
    )
