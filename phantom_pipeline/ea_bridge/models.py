"""EA Bridge input/output objects (`ADR-023` §4).

Every type here is a plain, immutable record of a transport-layer event
(a message received from the EA, a command relayed to it, a result
reported back) — never a re-derived trading instruction. `ExecutionCommand`
is built by `broker_adapter.EABrokerAdapter` from an already-produced
`mt5_bridge.models.BrokerRequest` verbatim; nothing in this module
computes a score, size, SL/TP, or verdict (`ADR-023` Hard Rule 1).

`execution_id`/`trace_id`/`request_kind` on `ExecutionCommand`/
`ExecutionReport` are the same identifiers `mt5_bridge` already generates
(`make_execution_id`) — this package invents no parallel ID scheme
(`ADR-023` Hard Rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..mt5_bridge.models import RequestKind
from ..scanner.models import Direction

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HeartbeatMessage:
    schema_version: int
    magic_number: int
    terminal_time: datetime
    account_login: Optional[int]
    connected: bool
    received_at: datetime


@dataclass(frozen=True)
class EAAccountState:
    """The EA's own reported account snapshot — a read model only.
    Never auto-converted into `risk_engine.models.AccountState`/
    `compliance_engine.models.AccountState`/`execution_validator.models.AccountState`
    by this package (`ADR-023` §7) — those require drawdown-curve
    tracking that `paper_trading.AccountTracker` already owns."""

    schema_version: int
    magic_number: int
    equity: float
    balance: float
    margin: Optional[float]
    free_margin: Optional[float]
    currency: str
    received_at: datetime


@dataclass(frozen=True)
class TickMessage:
    schema_version: int
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[float]
    terminal_time: datetime
    received_at: datetime


@dataclass(frozen=True)
class BarMessage:
    """One EA-reported bar (M15/H1/H4/D1). Forwarded verbatim to
    `data_pipeline.DataPipeline.load_historical_bars()` — this module
    performs no normalization of its own (`ADR-023` Hard Rule 3)."""

    schema_version: int
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_time: datetime
    received_at: datetime


@dataclass(frozen=True)
class PositionReport:
    schema_version: int
    position_id: str
    symbol: str
    direction: Direction
    volume: float
    open_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    unrealized_pnl: Optional[float]
    magic_number: int
    received_at: datetime


@dataclass(frozen=True)
class ExecutionCommand:
    """One command relayed to the EA — built only from an already-
    produced `mt5_bridge.models.BrokerRequest` by
    `broker_adapter.EABrokerAdapter.send_request()` (`ADR-023` Hard Rule
    4). No other code path in this package constructs one."""

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
    magic_number: int
    max_slippage_points: int
    issued_at: datetime


@dataclass(frozen=True)
class ExecutionReport:
    """The EA's report of what happened when it executed one
    `ExecutionCommand` — correlated by `execution_id` only."""

    schema_version: int
    execution_id: str
    magic_number: int
    success: bool
    broker_ticket: Optional[str]
    filled_price: Optional[float]
    filled_size: Optional[float]
    reason: Optional[str]
    reported_at: datetime


@dataclass(frozen=True)
class ErrorReport:
    schema_version: int
    magic_number: int
    code: Optional[int]
    message: str
    context: Optional[str]
    reported_at: datetime


@dataclass(frozen=True)
class EmergencyStopState:
    """`active=True` halts all new command issuance (`command_queue.py`)
    and is surfaced to the EA on its next `/ea/commands/poll` response so
    it can fail closed even if it never misses a heartbeat."""

    active: bool
    reason: Optional[str]
    activated_at: Optional[datetime]


__all__ = [
    "SCHEMA_VERSION",
    "HeartbeatMessage",
    "EAAccountState",
    "TickMessage",
    "BarMessage",
    "PositionReport",
    "ExecutionCommand",
    "ExecutionReport",
    "ErrorReport",
    "EmergencyStopState",
]
