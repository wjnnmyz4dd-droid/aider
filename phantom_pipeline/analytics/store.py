"""The trade-provenance collection store (ADR-010 §2, §4).

Analytics is the first stage in the pipeline whose entire purpose is to
accumulate state across many calls, keyed by `trace_id` — a deliberate
architectural difference from every prior decision-making stage (which
are pure functions of their inputs). This is authorized by ADR-010 §2's
"collect" responsibility itself, not a departure from determinism:
`build_provenance_record()` (`engine.py`) is still a pure function of
"what has been recorded for this `trace_id` so far," and recording the
same sequence of objects always produces the same accumulated state.

Each `record_*` method accepts the object *as produced by its origin
stage* — never re-derived, never mutated — and appends/sets it into an
internal, mutable bucket private to this store. The bucket itself is
never exposed as mutable state to callers; only `engine.py`'s
`build_provenance_record()` reads it, to construct an immutable
`TradeProvenanceRecord` snapshot.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple

from ..compliance_engine.models import ComplianceDecision
from ..data_pipeline.models import MarketSnapshot
from ..execution_validator.models import ExecutionDecision
from ..mt5_bridge.models import FillReport
from ..position_manager.models import PositionManagementDecision, PositionSynchronizationResult, PositionUpdate
from ..risk_engine.models import RiskDecision
from ..scanner.models import ScannerObservation
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade
from .models import BrokerEvent


class _TradeBucket:
    """Internal, mutable accumulator for one `trace_id` — never exposed
    outside this module; `engine.py` reads a snapshot of it, never the
    live object."""

    def __init__(self) -> None:
        self.scanner_observation: Optional[ScannerObservation] = None
        self.candidate: Optional[CandidateTrade] = None
        self.score_result: Optional[ScoreResult] = None
        self.risk_decision: Optional[RiskDecision] = None
        self.compliance_decision: Optional[ComplianceDecision] = None
        self.execution_decision: Optional[ExecutionDecision] = None
        self.broker_events: List[BrokerEvent] = []
        self.fill_reports: List[FillReport] = []
        self.position_management_decisions: List[PositionManagementDecision] = []
        self.position_updates: List[PositionUpdate] = []
        self.position_synchronization_results: List[PositionSynchronizationResult] = []
        self.account_snapshots: List[Any] = []
        self.market_snapshots: List[MarketSnapshot] = []


class TradeProvenanceStore(ABC):
    @abstractmethod
    def record_scanner_observation(self, trace_id: str, observation: ScannerObservation) -> None:
        ...

    @abstractmethod
    def record_candidate(self, trace_id: str, candidate: CandidateTrade) -> None:
        ...

    @abstractmethod
    def record_score_result(self, trace_id: str, score_result: ScoreResult) -> None:
        ...

    @abstractmethod
    def record_risk_decision(self, trace_id: str, risk_decision: RiskDecision) -> None:
        ...

    @abstractmethod
    def record_compliance_decision(self, trace_id: str, compliance_decision: ComplianceDecision) -> None:
        ...

    @abstractmethod
    def record_execution_decision(self, trace_id: str, execution_decision: ExecutionDecision) -> None:
        ...

    @abstractmethod
    def record_broker_event(self, trace_id: str, event: BrokerEvent) -> None:
        ...

    @abstractmethod
    def record_fill_report(self, trace_id: str, fill_report: FillReport) -> None:
        ...

    @abstractmethod
    def record_position_management_decision(self, trace_id: str, decision: PositionManagementDecision) -> None:
        ...

    @abstractmethod
    def record_position_update(self, trace_id: str, update: PositionUpdate) -> None:
        ...

    @abstractmethod
    def record_position_synchronization_result(
        self, trace_id: str, result: PositionSynchronizationResult
    ) -> None:
        ...

    @abstractmethod
    def record_account_snapshot(self, trace_id: str, snapshot: Any) -> None:
        ...

    @abstractmethod
    def record_market_snapshot(self, trace_id: str, snapshot: MarketSnapshot) -> None:
        ...

    @abstractmethod
    def get_bucket(self, trace_id: str) -> Optional[_TradeBucket]:
        ...

    @abstractmethod
    def known_trace_ids(self) -> Tuple[str, ...]:
        ...


class InMemoryTradeProvenanceStore(TradeProvenanceStore):
    def __init__(self) -> None:
        self._buckets: dict = {}

    def _bucket_for(self, trace_id: str) -> _TradeBucket:
        return self._buckets.setdefault(trace_id, _TradeBucket())

    def record_scanner_observation(self, trace_id: str, observation: ScannerObservation) -> None:
        self._bucket_for(trace_id).scanner_observation = observation

    def record_candidate(self, trace_id: str, candidate: CandidateTrade) -> None:
        self._bucket_for(trace_id).candidate = candidate

    def record_score_result(self, trace_id: str, score_result: ScoreResult) -> None:
        self._bucket_for(trace_id).score_result = score_result

    def record_risk_decision(self, trace_id: str, risk_decision: RiskDecision) -> None:
        self._bucket_for(trace_id).risk_decision = risk_decision

    def record_compliance_decision(self, trace_id: str, compliance_decision: ComplianceDecision) -> None:
        self._bucket_for(trace_id).compliance_decision = compliance_decision

    def record_execution_decision(self, trace_id: str, execution_decision: ExecutionDecision) -> None:
        self._bucket_for(trace_id).execution_decision = execution_decision

    def record_broker_event(self, trace_id: str, event: BrokerEvent) -> None:
        self._bucket_for(trace_id).broker_events.append(event)

    def record_fill_report(self, trace_id: str, fill_report: FillReport) -> None:
        self._bucket_for(trace_id).fill_reports.append(fill_report)

    def record_position_management_decision(self, trace_id: str, decision: PositionManagementDecision) -> None:
        self._bucket_for(trace_id).position_management_decisions.append(decision)

    def record_position_update(self, trace_id: str, update: PositionUpdate) -> None:
        self._bucket_for(trace_id).position_updates.append(update)

    def record_position_synchronization_result(
        self, trace_id: str, result: PositionSynchronizationResult
    ) -> None:
        self._bucket_for(trace_id).position_synchronization_results.append(result)

    def record_account_snapshot(self, trace_id: str, snapshot: Any) -> None:
        self._bucket_for(trace_id).account_snapshots.append(snapshot)

    def record_market_snapshot(self, trace_id: str, snapshot: MarketSnapshot) -> None:
        self._bucket_for(trace_id).market_snapshots.append(snapshot)

    def get_bucket(self, trace_id: str) -> Optional[_TradeBucket]:
        return self._buckets.get(trace_id)

    def known_trace_ids(self) -> Tuple[str, ...]:
        return tuple(self._buckets.keys())
