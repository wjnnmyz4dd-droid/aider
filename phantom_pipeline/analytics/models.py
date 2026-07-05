"""Analytics input/output objects (ADR-010 §2, §5, §6).

Analytics is Phantom's permanent institutional memory — it owns history,
not authority (§1). Every field on `TradeProvenanceRecord` holding an
upstream object is the *actual, immutable object itself* (`ScannerObservation`,
`CandidateTrade`, `ScoreResult`, `RiskDecision`, `ComplianceDecision`,
`ExecutionDecision`, MT5 Bridge/Position Manager event types) — never a
paraphrase, a re-derived summary, or a mutated copy. This directly
satisfies §2's "Configuration version"/"ADR version"/"Strategy version"
requirements too: every one of those objects already carries its own
`schema_version` and stage-version string (`risk_engine_version`,
`compliance_engine_version`, `execution_validator_version`,
`position_manager_version`, `CandidateTrade.strategy_version`) —
retaining the object intact retains its version metadata; no separate,
duplicate version-tracking type is needed or created here.

No field anywhere in this module is capable of representing a modified
copy of any collected object (§5's type-level guarantee) — Analytics
never mutates a source object at its origin stage, and never presents a
mutated copy as if it were the original.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Tuple, Union

from ..compliance_engine.models import ComplianceDecision
from ..data_pipeline.models import MarketSnapshot
from ..execution_validator.models import ExecutionDecision
from ..mt5_bridge.models import BrokerAcknowledgement, BrokerError, ExecutionReceipt, FillReport
from ..position_manager.models import PositionManagementDecision, PositionSynchronizationResult, PositionUpdate
from ..risk_engine.models import RiskDecision
from ..scanner.models import ScannerObservation
from ..scoring_engine.models import ScoreResult
from ..strategy_engine.models import CandidateTrade

SCHEMA_VERSION = 1

BrokerEvent = Union[BrokerAcknowledgement, ExecutionReceipt, BrokerError]


class OutcomeKind(Enum):
    """A trade's terminal (or current) state, as far as it has
    progressed (ADR-010 §6's "Final outcome"). `OPEN` means a position
    exists (at least one fill) but no close has been observed yet —
    not itself a terminal state, but the honest current state."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class FinalOutcome:
    """§6's "Final outcome — realized P/L, MAE, MFE, and close reason,
    if the trade reached a position at all; the terminal rejection
    reason and stage, if it did not." `mae`/`mfe` are the minimum/
    maximum unrealized P/L observed across every recorded `PositionUpdate`
    — a direct, non-fabricated computation over already-recorded values,
    never an estimate."""

    outcome_kind: OutcomeKind
    realized_pnl: Optional[float]
    mae: Optional[float]
    mfe: Optional[float]
    close_reason: Optional[str]
    rejected_at_stage: Optional[str]
    rejection_reason: Optional[str]


@dataclass(frozen=True)
class MissingEventReport:
    """A non-silent flag that a `trace_id`'s expected chain has a gap
    (ADR-010 §6, §12) — never a partial record silently presented as
    whole."""

    trace_id: str
    missing_fields: Tuple[str, ...]
    detail: str
    timestamp: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))


@dataclass(frozen=True)
class TradeProvenanceRecord:
    """The full joined decision-and-event history for one `trace_id`
    (ADR-010 §5, §6) — whether the trade was rejected at any stage or
    fully executed and closed. Immutable once produced (§5): a
    permanent historical record, not a mutable working object.

    `account_snapshots` is loosely typed (`Tuple[Any, ...]`) since no
    prior ADR defines a single canonical account-state type shared
    across stages — each of Risk Engine/Compliance Engine/Execution
    Validator/Position Manager already owns its own narrowly-scoped
    `AccountState` (a deliberate, documented design choice at each of
    those stages); Analytics collects whichever object the caller
    supplies without inventing a new unified type ADR-010 does not
    itself define.
    """

    schema_version: int
    trace_id: str
    scanner_observation: Optional[ScannerObservation]
    candidate: Optional[CandidateTrade]
    score_result: Optional[ScoreResult]
    risk_decision: Optional[RiskDecision]
    compliance_decision: Optional[ComplianceDecision]
    execution_decision: Optional[ExecutionDecision]
    broker_events: Tuple[BrokerEvent, ...]
    fill_reports: Tuple[FillReport, ...]
    position_management_decisions: Tuple[PositionManagementDecision, ...]
    position_updates: Tuple[PositionUpdate, ...]
    position_synchronization_results: Tuple[PositionSynchronizationResult, ...]
    account_snapshots: Tuple[Any, ...]
    market_snapshots: Tuple[MarketSnapshot, ...]
    final_outcome: Optional[FinalOutcome]
    analytics_version: str
    collected_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "broker_events", tuple(self.broker_events))
        object.__setattr__(self, "fill_reports", tuple(self.fill_reports))
        object.__setattr__(self, "position_management_decisions", tuple(self.position_management_decisions))
        object.__setattr__(self, "position_updates", tuple(self.position_updates))
        object.__setattr__(
            self, "position_synchronization_results", tuple(self.position_synchronization_results)
        )
        object.__setattr__(self, "account_snapshots", tuple(self.account_snapshots))
        object.__setattr__(self, "market_snapshots", tuple(self.market_snapshots))


@dataclass(frozen=True)
class ReplayInputSet:
    """The exact, ordered, immutable inputs a given `trace_id`'s stages
    saw (ADR-010 §8) — sufficient for an external replay/certification
    process (forward-declared to `ADR-018`, not resolved here) to
    reproduce each stage's decision. Derived directly from a
    `TradeProvenanceRecord` (never collected independently — "compute
    once, share the result"), so it can never drift from the record it
    was built from."""

    trace_id: str
    scanner_observation: Optional[ScannerObservation]
    candidate: Optional[CandidateTrade]
    score_result: Optional[ScoreResult]
    risk_decision: Optional[RiskDecision]
    compliance_decision: Optional[ComplianceDecision]
    execution_decision: Optional[ExecutionDecision]
    market_snapshots: Tuple[MarketSnapshot, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "market_snapshots", tuple(self.market_snapshots))


@dataclass(frozen=True)
class PerformanceStatistics:
    """Derived, read-only aggregates over one or more
    `TradeProvenanceRecord`s (ADR-010 §9) — computed from real recorded
    outcomes only, never fabricated, and structurally incapable of
    feeding back into any live decision (§3)."""

    trade_count: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    sharpe: Optional[float]
    sortino: Optional[float]
    expectancy: Optional[float]
    average_mae: Optional[float]
    average_mfe: Optional[float]
    max_drawdown: Optional[float]
    generated_at: datetime
    analytics_version: str
