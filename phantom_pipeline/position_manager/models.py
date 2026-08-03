"""Position Manager input/output objects (ADR-009 §5, §6, §7).

The Position Manager manages an already-open position's lifecycle
(§1) — it never creates trades, never modifies any upstream immutable
object (`ScannerObservation`, `ScoreResult`, `RiskDecision`,
`ComplianceDecision`, `ExecutionDecision`), and never talks to MT5
directly. Every field here is either a routine observation (`PositionUpdate`),
a decision record (`PositionManagementDecision`), or a request routed
back through MT5 Bridge for actual submission (`PositionAdjustmentRequest`/
`PositionCloseRequest`) — never a broker instruction executed by this
stage itself.

**Ownership note (ADR-009 §5, §9; `INTERFACE_SPECIFICATION.md`'s
authoritative ownership table attributes both types to `ADR-009` §5):**
`PositionAdjustmentRequest`/`PositionCloseRequest` were defined
provisionally in `mt5_bridge.models` during ADR-008 Phase 1, since
Position Manager did not yet exist as code and Amendment 1 required MT5
Bridge to accept this input contract immediately. Per this ADR's own
explicit instruction ("if ADR-009 explicitly transfers ownership...
perform that move exactly as specified"), the canonical definitions now
live here; `mt5_bridge.models` re-exports them unchanged (same class
objects, same import path, zero behavioral change to ADR-008) so no
ADR-002 through ADR-008 test or call site needed to change.

No field anywhere in this module is capable of representing a modified
upstream decision or a new `CandidateTrade` (ADR-009 §5's type-level
guarantee, Hard Rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..scanner.models import Direction

SCHEMA_VERSION = 1


class LifecycleState(Enum):
    """A position's lifecycle stage (ADR-009 §7) — tracked by this stage
    from fill to close. `RECOVERED`/`RECOVERED_AFTER_DISCONNECT` may
    interrupt any other state (§7)."""

    OPEN = "OPEN"
    FILLED = "FILLED"
    PROTECTED = "PROTECTED"
    TRAILING = "TRAILING"
    SCALING = "SCALING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    RECOVERED = "RECOVERED"
    RECOVERED_AFTER_DISCONNECT = "RECOVERED_AFTER_DISCONNECT"


class ManagementAction(Enum):
    """The exhaustive action vocabulary (ADR-009 §6). `MOVE_STOP_LOSS` is
    reserved for an explicit, externally-requested manual adjustment
    (`checks.stop_loss_adjustment`) — no autonomous Phase 1 rule
    independently invents this action, per the Hard Rule "never invent
    management actions."."""

    NO_ACTION = "NO_ACTION"
    MOVE_TO_BREAKEVEN = "MOVE_TO_BREAKEVEN"
    MOVE_STOP_LOSS = "MOVE_STOP_LOSS"
    TRAIL_STOP = "TRAIL_STOP"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    TIME_EXIT = "TIME_EXIT"
    EMERGENCY_CLOSE = "EMERGENCY_CLOSE"


class RuleStatus(Enum):
    """Every gate/rule's individual evaluation result (ADR-009 §12's
    per-action attributability, applying the same explainability
    discipline `ADR-006`/`ADR-007` already established to this stage's
    own gates and rules). For a *gate*, `TRIGGERED` means "this gate
    blocks management" and `UNEVALUABLE` blocks identically (fail-closed,
    §10 Hard Rule: "if synchronization cannot be restored: freeze
    management... never guess"). For a *rule*, `TRIGGERED` means "this
    rule's action should fire"; `UNEVALUABLE` simply means this rule
    contributes nothing to the final action this evaluation — it does
    not, by itself, force a HOLD (only gates do)."""

    NOT_TRIGGERED = "NOT_TRIGGERED"
    TRIGGERED = "TRIGGERED"
    UNEVALUABLE = "UNEVALUABLE"


@dataclass(frozen=True)
class RuleEvaluation:
    """One gate's or rule's independent evaluation — always computed,
    never short-circuited (this ADR's own explicit instruction), so
    `PositionManagementDecision.rule_evaluations` is always the complete
    audit trail."""

    rule: str
    status: RuleStatus
    detail: str


@dataclass(frozen=True)
class PositionManagementDecision:
    """One position's management decision for this evaluation (ADR-009
    §6). Immutable once produced. `action` is `NO_ACTION` (a "HOLD")
    whenever any gate blocks, or when no rule triggers — the fail-closed
    default (§10 Hard Rule), never a guess.

    `trace_id` is inherited from the position's originating
    `ExecutionDecision` verbatim (§6), extending the trace chain
    established at every prior stage."""

    schema_version: int
    position_id: str
    trace_id: str
    action: ManagementAction
    decision_reason: str
    rule_evaluations: Tuple[RuleEvaluation, ...]
    timestamp: datetime
    position_manager_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_evaluations", tuple(self.rule_evaluations))


@dataclass(frozen=True)
class PositionUpdate:
    """A routine state update (ADR-009 §5) — P/L and current lifecycle
    stage; never itself a request for broker action."""

    schema_version: int
    position_id: str
    trace_id: str
    lifecycle_state: LifecycleState
    unrealized_pnl: Optional[float]
    current_price: Optional[float]
    timestamp: datetime


@dataclass(frozen=True)
class PositionSynchronizationResult:
    """The outcome of reconciling Live Position State against Broker
    Position State (ADR-009 §8) after an `ADR-008` `SynchronizationStatus`
    discrepancy or a reconnect event. Broker-side truth is always ground
    truth for reconciliation — never the reverse (§8)."""

    schema_version: int
    position_id: str
    trace_id: str
    lifecycle_state: LifecycleState
    broker_position_found: bool
    detail: str
    timestamp: datetime


@dataclass(frozen=True)
class PositionAdjustmentRequest:
    """A request to modify SL/TP (break-even, trailing, or an explicit
    manual adjustment) on an open position (ADR-009 §5) — routed to MT5
    Bridge for execution, never sent to the broker directly (Hard
    Rules). See the module docstring for this type's ownership history."""

    schema_version: int
    execution_id: str
    trace_id: str
    position_id: str
    new_stop_loss: Optional[float]
    new_take_profit: Optional[float]
    timestamp: datetime


@dataclass(frozen=True)
class PositionCloseRequest:
    """A request (full or partial) to close a position (ADR-009 §5) —
    routed to MT5 Bridge for execution, never sent to the broker
    directly (Hard Rules). `close_fraction` of `1.0` is a full close; any
    value in `(0.0, 1.0)` is a partial close. See the module docstring
    for this type's ownership history."""

    schema_version: int
    execution_id: str
    trace_id: str
    position_id: str
    close_fraction: float
    timestamp: datetime


@dataclass(frozen=True)
class LivePositionState:
    """This stage's own tracked view of one open position (ADR-009 §4,
    §7) — supplied fresh by the caller on each `evaluate()` call, never
    read from hidden internal mutable state, so identical inputs always
    produce identical decisions (§11 determinism).

    `current_stop_loss`/`current_take_profit` are the position's
    presently-set levels. No upstream ADR through ADR-008 persists these
    on any object (the same documented Phase 1 gap `RiskEngine.decide`'s
    `stop_distance`, `ExecutionValidator.validate`'s
    `intended_stop_loss`/`intended_take_profit`, and `MT5Bridge.
    submit_order`'s `stop_loss`/`take_profit` parameters already
    establish) — the caller is responsible for tracking and supplying
    them here."""

    position_id: str
    trace_id: str
    direction: Direction
    entry_price: float
    lifecycle_state: LifecycleState
    current_stop_loss: Optional[float]
    current_take_profit: Optional[float]
    remaining_fraction: float
    opened_at: datetime
