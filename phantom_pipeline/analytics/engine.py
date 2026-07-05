"""The Analytics Engine (ADR-010).

`AnalyticsEngine` collects immutable, read-only copies of every object
every prior stage produces (§2), keyed by `trace_id`, and on demand
builds an immutable `TradeProvenanceRecord` (§5, §6) — Phantom's
permanent institutional memory. It never mutates a collected object,
never feeds anything back into a live decision, and holds no
order-placement or position-management capability whatsoever (§3, §11).

`build_provenance_record()` infers `FinalOutcome` (§6) purely from
already-recorded facts:

- A `ComplianceDecision` of `BLOCK` or an `ExecutionDecision` of `REJECT`
  terminates the trade at that stage — `OutcomeKind.REJECTED`.
- At least one `FillReport` means a position exists. If any recorded
  `PositionUpdate.lifecycle_state` is `CLOSED`, the trade is
  `OutcomeKind.CLOSED`; otherwise `OutcomeKind.OPEN`.
- No fill and no rejection yet means the trade has no outcome to report
  at all (`None`) — it is simply still in progress through the pipeline,
  not a defect (`checks.detect_issues` is the mechanism for genuine
  gaps, not this inference).

MAE/MFE are the minimum/maximum `unrealized_pnl` observed across every
recorded `PositionUpdate` for that `trace_id` — a direct computation
over already-recorded values, never an estimate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple

from ..compliance_engine.models import ComplianceDecision, Verdict as ComplianceVerdict
from ..data_pipeline.models import MarketSnapshot
from ..execution_validator.models import ExecutionDecision, Verdict as ExecutionVerdict
from ..position_manager.models import (
    LifecycleState,
    ManagementAction,
    PositionManagementDecision,
    PositionSynchronizationResult,
    PositionUpdate,
)
from ..risk_engine.models import RiskDecision
from ..scanner.models import ScannerObservation
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade
from ..strategy_engine.registry import StrategyRegistry
from . import attribution, checks, performance
from .config import ANALYTICS_VERSION, DEFAULT_CONFIG, AnalyticsConfig
from .logging_sink import (
    log_collected,
    log_missing_event,
    log_performance_statistics,
    log_provenance_record,
    log_replay_input_set,
)
from .metrics import AnalyticsMetrics
from .models import (
    SCHEMA_VERSION,
    BrokerEvent,
    FinalOutcome,
    MissingEventReport,
    OutcomeKind,
    PerformanceStatistics,
    ReplayInputSet,
    TradeProvenanceRecord,
)
from .store import TradeProvenanceStore

_TERMINAL_CLOSE_ACTIONS = (ManagementAction.TIME_EXIT, ManagementAction.EMERGENCY_CLOSE, ManagementAction.PARTIAL_CLOSE)


class AnalyticsEngine:
    def __init__(
        self,
        store: TradeProvenanceStore,
        config: AnalyticsConfig = DEFAULT_CONFIG,
        metrics: Optional[AnalyticsMetrics] = None,
    ):
        self.store = store
        self.config = config
        self.metrics = metrics

    # -- Collection (§2) --------------------------------------------------

    def collect_scanner_observation(self, trace_id: str, observation: ScannerObservation) -> None:
        self.store.record_scanner_observation(trace_id, observation)
        self._log_and_meter(trace_id, "scanner_observation")

    def collect_candidate(self, trace_id: str, candidate: CandidateTrade) -> None:
        self.store.record_candidate(trace_id, candidate)
        self._log_and_meter(trace_id, "candidate")

    def collect_score_result(self, trace_id: str, score_result: ScoreResult) -> None:
        self.store.record_score_result(trace_id, score_result)
        self._log_and_meter(trace_id, "score_result")

    def collect_risk_decision(self, trace_id: str, risk_decision: RiskDecision) -> None:
        self.store.record_risk_decision(trace_id, risk_decision)
        self._log_and_meter(trace_id, "risk_decision")

    def collect_compliance_decision(self, trace_id: str, compliance_decision: ComplianceDecision) -> None:
        self.store.record_compliance_decision(trace_id, compliance_decision)
        self._log_and_meter(trace_id, "compliance_decision")

    def collect_execution_decision(self, trace_id: str, execution_decision: ExecutionDecision) -> None:
        self.store.record_execution_decision(trace_id, execution_decision)
        self._log_and_meter(trace_id, "execution_decision")

    def collect_broker_event(self, trace_id: str, event: BrokerEvent) -> None:
        self.store.record_broker_event(trace_id, event)
        self._log_and_meter(trace_id, "broker_event")

    def collect_fill_report(self, trace_id: str, fill_report) -> None:
        self.store.record_fill_report(trace_id, fill_report)
        self._log_and_meter(trace_id, "fill_report")

    def collect_position_management_decision(self, trace_id: str, decision: PositionManagementDecision) -> None:
        self.store.record_position_management_decision(trace_id, decision)
        self._log_and_meter(trace_id, "position_management_decision")

    def collect_position_update(self, trace_id: str, update: PositionUpdate) -> None:
        self.store.record_position_update(trace_id, update)
        self._log_and_meter(trace_id, "position_update")

    def collect_position_synchronization_result(
        self, trace_id: str, result: PositionSynchronizationResult
    ) -> None:
        self.store.record_position_synchronization_result(trace_id, result)
        self._log_and_meter(trace_id, "position_synchronization_result")

    def collect_account_snapshot(self, trace_id: str, snapshot: Any) -> None:
        self.store.record_account_snapshot(trace_id, snapshot)
        self._log_and_meter(trace_id, "account_snapshot")

    def collect_market_snapshot(self, trace_id: str, snapshot: MarketSnapshot) -> None:
        self.store.record_market_snapshot(trace_id, snapshot)
        self._log_and_meter(trace_id, "market_snapshot")

    def _log_and_meter(self, trace_id: str, kind: str) -> None:
        log_collected(trace_id, kind)
        if self.metrics is not None:
            self.metrics.record_collected(kind)

    # -- Provenance (§5, §6) ----------------------------------------------

    def build_provenance_record(self, trace_id: str, now: datetime) -> Optional[TradeProvenanceRecord]:
        bucket = self.store.get_bucket(trace_id)
        if bucket is None:
            return None

        final_outcome = self._infer_final_outcome(bucket)
        record = TradeProvenanceRecord(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            scanner_observation=bucket.scanner_observation,
            candidate=bucket.candidate,
            score_result=bucket.score_result,
            risk_decision=bucket.risk_decision,
            compliance_decision=bucket.compliance_decision,
            execution_decision=bucket.execution_decision,
            broker_events=tuple(bucket.broker_events),
            fill_reports=tuple(bucket.fill_reports),
            position_management_decisions=tuple(bucket.position_management_decisions),
            position_updates=tuple(bucket.position_updates),
            position_synchronization_results=tuple(bucket.position_synchronization_results),
            account_snapshots=tuple(bucket.account_snapshots),
            market_snapshots=tuple(bucket.market_snapshots),
            final_outcome=final_outcome,
            analytics_version=ANALYTICS_VERSION,
            collected_at=now,
        )
        log_provenance_record(record)
        if self.metrics is not None:
            self.metrics.record_provenance_record_built()
        return record

    def _infer_final_outcome(self, bucket) -> Optional[FinalOutcome]:
        if bucket.compliance_decision is not None and bucket.compliance_decision.verdict == ComplianceVerdict.BLOCK:
            return FinalOutcome(
                outcome_kind=OutcomeKind.REJECTED,
                realized_pnl=None,
                mae=None,
                mfe=None,
                close_reason=None,
                rejected_at_stage="compliance_engine",
                rejection_reason="+".join(bucket.compliance_decision.blocking_rules),
            )
        if bucket.execution_decision is not None and bucket.execution_decision.verdict == ExecutionVerdict.REJECT:
            return FinalOutcome(
                outcome_kind=OutcomeKind.REJECTED,
                realized_pnl=None,
                mae=None,
                mfe=None,
                close_reason=None,
                rejected_at_stage="execution_validator",
                rejection_reason="+".join(bucket.execution_decision.blocking_reasons),
            )
        if not bucket.fill_reports:
            return None

        pnl_series = [u.unrealized_pnl for u in bucket.position_updates if u.unrealized_pnl is not None]
        mae = min(pnl_series) if pnl_series else None
        mfe = max(pnl_series) if pnl_series else None
        closed = any(u.lifecycle_state == LifecycleState.CLOSED for u in bucket.position_updates)

        if not closed:
            return FinalOutcome(
                outcome_kind=OutcomeKind.OPEN, realized_pnl=None, mae=mae, mfe=mfe,
                close_reason=None, rejected_at_stage=None, rejection_reason=None,
            )

        realized_pnl = pnl_series[-1] if pnl_series else None
        close_decision = next(
            (d for d in reversed(bucket.position_management_decisions) if d.action in _TERMINAL_CLOSE_ACTIONS),
            None,
        )
        close_reason = close_decision.decision_reason if close_decision is not None else None
        return FinalOutcome(
            outcome_kind=OutcomeKind.CLOSED, realized_pnl=realized_pnl, mae=mae, mfe=mfe,
            close_reason=close_reason, rejected_at_stage=None, rejection_reason=None,
        )

    # -- Completeness (§6, §12) --------------------------------------------

    def check_completeness(self, trace_id: str, now: datetime) -> Optional[MissingEventReport]:
        record = self.build_provenance_record(trace_id, now)
        if record is None:
            return MissingEventReport(trace_id=trace_id, missing_fields=("all",), detail="trace_id never observed", timestamp=now)
        report = checks.detect_issues(record, now)
        if report is not None:
            log_missing_event(report)
            if self.metrics is not None:
                self.metrics.record_missing_event()
        return report

    # -- Replay (§8) --------------------------------------------------------

    def build_replay_input_set(self, trace_id: str, now: datetime) -> Optional[ReplayInputSet]:
        record = self.build_provenance_record(trace_id, now)
        if record is None:
            return None
        replay_set = ReplayInputSet(
            trace_id=record.trace_id,
            scanner_observation=record.scanner_observation,
            candidate=record.candidate,
            score_result=record.score_result,
            risk_decision=record.risk_decision,
            compliance_decision=record.compliance_decision,
            execution_decision=record.execution_decision,
            market_snapshots=record.market_snapshots,
            generated_at=now,
        )
        log_replay_input_set(replay_set)
        if self.metrics is not None:
            self.metrics.record_replay_input_set_built()
        return replay_set

    # -- Performance (§9) -----------------------------------------------

    def compute_performance_statistics(
        self, records: Sequence[TradeProvenanceRecord], now: datetime
    ) -> PerformanceStatistics:
        stats = performance.compute_performance_statistics(records, now)
        log_performance_statistics(stats)
        if self.metrics is not None:
            self.metrics.record_performance_statistics_computed()
        return stats

    def group_by_strategy(
        self, records: Sequence[TradeProvenanceRecord], registry: StrategyRegistry
    ) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
        return attribution.group_by_strategy(records, registry)

    def group_by_regime(self, records: Sequence[TradeProvenanceRecord]) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
        return attribution.group_by_regime(records)

    def group_by_session(self, records: Sequence[TradeProvenanceRecord]) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
        return attribution.group_by_session(records)

    def group_by_pair(self, records: Sequence[TradeProvenanceRecord]) -> Dict[str, Tuple[TradeProvenanceRecord, ...]]:
        return attribution.group_by_pair(records)
