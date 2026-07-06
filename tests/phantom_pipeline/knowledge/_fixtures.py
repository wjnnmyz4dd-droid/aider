"""Shared test-only fixtures for the Knowledge & RAG subsystem tests —
builds a synthetic but real-shaped `TradeProvenanceRecord` (executed or
rejected) and a full `ScannerObservation` for session/regime-extraction
tests, mirroring `tests/phantom_pipeline/orchestrator/_fixtures.py`'s own
style.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from phantom_pipeline.analytics.models import FinalOutcome, OutcomeKind, TradeProvenanceRecord
from phantom_pipeline.compliance_engine.models import ComplianceDecision
from phantom_pipeline.compliance_engine.models import Verdict as ComplianceVerdict
from phantom_pipeline.execution_validator.models import ExecutionDecision
from phantom_pipeline.execution_validator.models import Verdict as ExecutionVerdict
from phantom_pipeline.mt5_bridge.models import FillReport
from phantom_pipeline.position_manager.models import LifecycleState, ManagementAction, PositionManagementDecision, PositionUpdate, RuleEvaluation, RuleStatus
from phantom_pipeline.risk_engine.models import RiskDecision, RiskTier
from phantom_pipeline.scanner.models import (
    DataQualityFlag,
    Direction,
    MarketPhase,
    RangeStructure,
    ScannerObservation,
    SessionState,
    StructureConfidence,
    StructureTrendState,
    SwingSequenceType,
    VolatilityLabel,
    VolatilityState,
)
from phantom_pipeline.scoring_engine.models import ScoreResult
from phantom_pipeline.strategy_engine.models import CandidateTrade, Evidence, SupportingObservation

SYMBOL = "EURUSD"
STRATEGY_ID = "ORB_BREAKOUT"
T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_scanner_observation(
    trace_id: str = "trace-1", sessions: Tuple[str, ...] = ("LONDON",), phase: MarketPhase = MarketPhase.MARKUP
) -> ScannerObservation:
    return ScannerObservation(
        schema_version=1,
        trace_id=trace_id,
        symbol=SYMBOL,
        timestamp=T0,
        trend={},
        structure=(),
        volatility=VolatilityState(VolatilityLabel.NORMAL, 0.001),
        session=SessionState(active_sessions=sessions, window_position=0.5),
        liquidity_events=(),
        data_quality_flag=DataQualityFlag.NOMINAL,
        external_structure=StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS),
        internal_structure=StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS),
        swing_hierarchy=(),
        equal_highs=(),
        equal_lows=(),
        range_structure=RangeStructure.EXPANSION,
        phase=phase,
        trend_acceleration=True,
        trend_exhaustion=False,
        structure_confidence=StructureConfidence.CLEAR,
    )


def make_candidate(trace_id: str = "trace-1", entry_concept: str = "session breakout with BOS confirmation") -> CandidateTrade:
    return CandidateTrade(
        schema_version=1,
        trace_id=trace_id,
        candidate_id=f"cand-{trace_id}",
        strategy_id=STRATEGY_ID,
        strategy_version="1.0.0",
        symbol=SYMBOL,
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        entry_concept=entry_concept,
        supporting_observations=(SupportingObservation("trend", "up"),),
        evidence=(Evidence("structure", "BOS confirmed on M1"),),
        reason_codes=("TREND_ALIGNED",),
        reasoning="London session breakout following a liquidity sweep and BOS.",
    )


def make_score_result(candidate: CandidateTrade, overall_score: float = 75.0) -> ScoreResult:
    return ScoreResult(
        schema_version=1,
        trace_id=candidate.trace_id,
        candidate_id=candidate.candidate_id,
        strategy_id=candidate.strategy_id,
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        timestamp=T0,
        overall_score=overall_score,
        factor_breakdown=(),
        rule_contributions=(),
        confidence_rationale="strong trend alignment",
        scoring_version="1.0.0",
    )


def make_risk_decision(
    trace_id: str = "trace-1", tier: RiskTier = RiskTier.NORMAL, approved_risk_percent: float = 1.0
) -> RiskDecision:
    return RiskDecision(
        schema_version=1,
        trace_id=trace_id,
        candidate_id=f"cand-{trace_id}",
        strategy_id=STRATEGY_ID,
        symbol=SYMBOL,
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        approved_risk_percent=approved_risk_percent,
        approved_risk_amount=approved_risk_percent * 100.0,
        lot_size=0.1,
        risk_tier=tier,
        limiting_constraint="CORRELATION_EXPOSURE",
        constraint_evaluations=(),
        reason_codes=("WITHIN_LIMITS",) if tier != RiskTier.HALTED else ("MISSING_ACCOUNT_STATE",),
        risk_engine_version="1.0.0-phase1",
    )


def make_compliance_decision(trace_id: str = "trace-1", approve: bool = True) -> ComplianceDecision:
    verdict = ComplianceVerdict.APPROVE if approve else ComplianceVerdict.BLOCK
    return ComplianceDecision(
        schema_version=1,
        trace_id=trace_id,
        candidate_id=f"cand-{trace_id}",
        strategy_id=STRATEGY_ID,
        symbol=SYMBOL,
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        verdict=verdict,
        blocking_rules=() if approve else ("NEWS_BLACKOUT",),
        reason_codes=("SPREAD_OK", "NEWS_CLEAR") if approve else ("NEWS_BLACKOUT",),
        check_evaluations=(),
        compliance_engine_version="1.0.0-phase1",
    )


def make_execution_decision(trace_id: str = "trace-1", approve: bool = True) -> ExecutionDecision:
    verdict = ExecutionVerdict.APPROVE if approve else ExecutionVerdict.REJECT
    return ExecutionDecision(
        schema_version=1,
        trace_id=trace_id,
        candidate_id=f"cand-{trace_id}",
        strategy_id=STRATEGY_ID,
        symbol=SYMBOL,
        timeframe="M1",
        timestamp=T0,
        direction=Direction.UP,
        verdict=verdict,
        blocking_reasons=() if approve else ("BROKER_CONNECTION_HEALTHY",),
        reason_codes=("SLIPPAGE_WITHIN_LIMITS",) if approve else ("BROKER_CONNECTION_HEALTHY",),
        warnings=(),
        check_evaluations=(),
        execution_validator_version="1.0.0-phase1",
    )


def make_position_management_decision(
    trace_id: str = "trace-1", action: ManagementAction = ManagementAction.MOVE_TO_BREAKEVEN
) -> PositionManagementDecision:
    return PositionManagementDecision(
        schema_version=1,
        position_id=f"pos-{trace_id}",
        trace_id=trace_id,
        action=action,
        decision_reason="price moved favorably past the breakeven trigger",
        rule_evaluations=(RuleEvaluation("MOVE_TO_BREAKEVEN", RuleStatus.TRIGGERED, "favorable distance reached"),),
        timestamp=T0,
        position_manager_version="1.0.0-phase1",
    )


def make_trade_provenance_record(
    trace_id: str = "trace-1",
    executed: bool = True,
    realized_pnl: Optional[float] = 50.0,
    include_scanner_observation: bool = True,
    sessions: Tuple[str, ...] = ("LONDON",),
    phase: MarketPhase = MarketPhase.MARKUP,
    position_management_decisions: Tuple[PositionManagementDecision, ...] = (),
) -> TradeProvenanceRecord:
    candidate = make_candidate(trace_id)
    score_result = make_score_result(candidate)
    risk_decision = make_risk_decision(trace_id, tier=RiskTier.NORMAL if executed else RiskTier.HALTED)
    compliance_decision = make_compliance_decision(trace_id, approve=executed)
    execution_decision = make_execution_decision(trace_id, approve=executed)

    if executed:
        final_outcome = FinalOutcome(
            outcome_kind=OutcomeKind.CLOSED, realized_pnl=realized_pnl, mae=-10.0, mfe=60.0,
            close_reason="TIME_EXIT", rejected_at_stage=None, rejection_reason=None,
        )
        fill_reports = (FillReport(schema_version=1, execution_id=f"exec-{trace_id}", trace_id=trace_id, fill_price=1.1000, fill_size=0.1, fill_timestamp=T0),)
        position_updates = (
            PositionUpdate(schema_version=1, position_id=f"pos-{trace_id}", trace_id=trace_id, lifecycle_state=LifecycleState.CLOSED, unrealized_pnl=0.0, current_price=1.1050, timestamp=T0),
        )
    else:
        final_outcome = FinalOutcome(
            outcome_kind=OutcomeKind.REJECTED, realized_pnl=None, mae=None, mfe=None,
            close_reason=None, rejected_at_stage="ComplianceEngine", rejection_reason="NEWS_BLACKOUT",
        )
        fill_reports = ()
        position_updates = ()

    return TradeProvenanceRecord(
        schema_version=1,
        trace_id=trace_id,
        scanner_observation=make_scanner_observation(trace_id, sessions, phase) if include_scanner_observation else None,
        candidate=candidate,
        score_result=score_result,
        risk_decision=risk_decision,
        compliance_decision=compliance_decision,
        execution_decision=execution_decision,
        broker_events=(),
        fill_reports=fill_reports,
        position_management_decisions=position_management_decisions,
        position_updates=position_updates,
        position_synchronization_results=(),
        account_snapshots=(),
        market_snapshots=(),
        final_outcome=final_outcome,
        analytics_version="1.0.0-phase1",
        collected_at=T0,
    )
