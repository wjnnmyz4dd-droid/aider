"""MT5 Bridge input/output objects (ADR-008 §4, §5, Amendment 1).

The MT5 Bridge is a translation and transport layer — every output type
here is a record of an event (a request sent, a broker reply received, a
connection/synchronization state observed), never a re-derived trading
instruction. Fields are populated by direct, faithful mapping from
already-decided upstream objects (`CandidateTrade`, `RiskDecision`,
`ExecutionDecision`) or from the broker adapter's own reply — this
module holds no logic capable of computing a new score, size, SL/TP, or
verdict (ADR-008 Hard Rules, §3).

`PositionAdjustmentRequest`/`PositionCloseRequest` are ADR-009 §5's
output types, defined here only because Position Manager (ADR-009) has
not been implemented as code yet and Amendment 1 requires MT5 Bridge to
accept this input contract now. Ownership of *deciding* to produce one
remains Position Manager's, once built — MT5 Bridge only ever consumes
these types, never constructs one on its own account (ADR-008 Hard
Rules: "Accept `PositionAdjustmentRequest` and `PositionCloseRequest`
only from Position Manager").

No field anywhere in this module is capable of representing a modified
upstream decision or a new/re-derived trading instruction (ADR-008 §5's
type-level guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..scanner.models import Direction

SCHEMA_VERSION = 1


class ConnectionState(Enum):
    """The connection state machine's position (ADR-008 §6) — at minimum
    these five states, in this order on the happy path. Any detected
    failure transitions back toward `DISCONNECTED`, never remains in a
    stale `READY`."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SYNCHRONIZING = "SYNCHRONIZING"
    READY = "READY"


class RequestKind(Enum):
    """Which originating request a transport-layer event correlates to
    (ADR-008 Amendment 1: "event-shaped, not opening-trade-shaped") — the
    same four output types now generalize across all three."""

    OPEN = "OPEN"
    ADJUST = "ADJUST"
    CLOSE = "CLOSE"


@dataclass(frozen=True)
class BrokerRequest:
    """The translated MT5 request actually submitted (ADR-008 §5),
    correlated to its originating decision by `trace_id` and this
    stage's own `execution_id` (§7). A direct field mapping from
    `CandidateTrade`/`RiskDecision`/`ExecutionDecision` (or, for
    Amendment 1 requests, from `PositionAdjustmentRequest`/
    `PositionCloseRequest`) — never a re-derivation.

    `stop_loss`/`take_profit` are `Optional[float]` because no upstream
    ADR through ADR-007 carries a stop-loss/take-profit price field on
    any persisted object (the same known Phase 1 gap `RiskEngine.decide`
    's `stop_distance` and `ExecutionValidator.validate`'s
    `intended_stop_loss`/`intended_take_profit` parameters already
    document) — callers of `MT5Bridge.submit_order` supply them
    explicitly; `None` means no SL/TP was supplied for this request, not
    that a lookup failed.

    A single generalized shape covers all three `RequestKind`s (ADR-008
    Amendment 1: "the same four types now also correlate to... no new
    output type is introduced"): `symbol`/`direction`/`lot_size`/
    `candidate_id` are populated only for `OPEN` (a fresh candidate
    exists); `position_id` is populated only for `ADJUST`/`CLOSE`
    (an existing position, not a fresh candidate); `close_fraction` is
    populated only for `CLOSE`. Each field is `None` when the
    corresponding `RequestKind` does not apply — never a placeholder
    value standing in for "not applicable."
    """

    schema_version: int
    execution_id: str
    trace_id: str
    request_kind: RequestKind
    symbol: Optional[str]
    direction: Optional[Direction]
    lot_size: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_id: Optional[str]
    close_fraction: Optional[float]
    candidate_id: Optional[str]
    timestamp: datetime


@dataclass(frozen=True)
class BrokerAcknowledgement:
    """The broker's receipt confirmation that a request arrived —
    distinct from execution (ADR-008 §5)."""

    schema_version: int
    execution_id: str
    trace_id: str
    request_kind: RequestKind
    broker_ref: Optional[str]
    timestamp: datetime


@dataclass(frozen=True)
class ExecutionReceipt:
    """Confirmation that an order was executed by the broker (ADR-008 §5)."""

    schema_version: int
    execution_id: str
    trace_id: str
    request_kind: RequestKind
    broker_ref: Optional[str]
    filled_price: Optional[float]
    filled_size: Optional[float]
    timestamp: datetime


@dataclass(frozen=True)
class BrokerError:
    """A rejection reason returned by the broker (ADR-008 §5) — distinct
    from a Phantom-side reject, which never reaches the broker at all
    (`reject_phantom_side` in `checks.py`)."""

    schema_version: int
    execution_id: str
    trace_id: str
    request_kind: RequestKind
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class FillReport:
    """Fill price, size, and timestamp for a submitted order (ADR-008 §5)."""

    schema_version: int
    execution_id: str
    trace_id: str
    fill_price: float
    fill_size: float
    fill_timestamp: datetime


@dataclass(frozen=True)
class ConnectionStatus:
    """The connection state-machine's current position, updated on every
    transition (ADR-008 §5, §6)."""

    schema_version: int
    state: ConnectionState
    detail: str
    timestamp: datetime


@dataclass(frozen=True)
class SynchronizationStatus:
    """The outcome of the most recent reconciliation between Phantom's
    expected state and MT5's actual state (ADR-008 §5, §9) — the signal
    Position Manager is expected to consume before acting on positions.
    A non-empty `discrepancies` means new order submission is halted
    (ADR-008 §8)."""

    schema_version: int
    in_sync: bool
    discrepancies: Tuple[str, ...]
    timestamp: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "discrepancies", tuple(self.discrepancies))


@dataclass(frozen=True)
class PositionAdjustmentRequest:
    """ADR-009 §5's SL/TP-modification request shape (break-even,
    trailing) — accepted only from Position Manager, defined here
    provisionally since ADR-009 is not yet implemented as code (see
    module docstring)."""

    schema_version: int
    execution_id: str
    trace_id: str
    position_id: str
    new_stop_loss: Optional[float]
    new_take_profit: Optional[float]
    timestamp: datetime


@dataclass(frozen=True)
class PositionCloseRequest:
    """ADR-009 §5's close request shape (full or partial) — accepted
    only from Position Manager, defined here provisionally since ADR-009
    is not yet implemented as code (see module docstring).
    `close_fraction` of `1.0` is a full close; any value in `(0.0, 1.0)`
    is a partial close."""

    schema_version: int
    execution_id: str
    trace_id: str
    position_id: str
    close_fraction: float
    timestamp: datetime
