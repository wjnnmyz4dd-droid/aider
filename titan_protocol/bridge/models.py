"""Wire-message types for the TitanProtocolEA transport (Phase 1).

Every type here is a plain, immutable record of a transport-layer event
-- a message received from the EA, a command relayed to it, or a result
reported back. Nothing here computes a trading decision: this package
is the single execution authority, never a decision authority. All
identifiers are correlation IDs supplied by the caller submitting a
command, never invented from data received off the wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

SCHEMA_VERSION = 1


class CommandKind(Enum):
    """The six trade-execution responsibilities this phase implements --
    deliberately no more, no fewer."""

    BUY = "BUY"
    SELL = "SELL"
    MODIFY_SL = "MODIFY_SL"
    MODIFY_TP = "MODIFY_TP"
    CLOSE = "CLOSE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"


class PositionDirection(Enum):
    """A factual position-side label, distinct from any future market-
    direction concept a Scanner component might compute."""

    BUY = "BUY"
    SELL = "SELL"


class ErrorCode(Enum):
    """Stable, named rejection/error reasons -- never a raw platform
    error code surfaced to a caller without translation."""

    MISSING_API_KEY = "MISSING_API_KEY"
    INVALID_API_KEY = "INVALID_API_KEY"
    MAGIC_NUMBER_MISMATCH = "MAGIC_NUMBER_MISMATCH"
    SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"
    INVALID_VOLUME = "INVALID_VOLUME"
    VOLUME_EXCEEDS_MAX = "VOLUME_EXCEEDS_MAX"
    INVALID_STOP_LOSS = "INVALID_STOP_LOSS"
    INVALID_TAKE_PROFIT = "INVALID_TAKE_PROFIT"
    TIMESTAMP_IN_FUTURE = "TIMESTAMP_IN_FUTURE"
    STALE_TIMESTAMP = "STALE_TIMESTAMP"
    MISSING_CORRELATION_ID = "MISSING_CORRELATION_ID"
    DUPLICATE_CORRELATION_ID = "DUPLICATE_CORRELATION_ID"
    UNKNOWN_CORRELATION_ID = "UNKNOWN_CORRELATION_ID"
    BRIDGE_NOT_READY = "BRIDGE_NOT_READY"
    EMERGENCY_STOP_ACTIVE = "EMERGENCY_STOP_ACTIVE"


@dataclass(frozen=True)
class HeartbeatMessage:
    schema_version: int
    magic_number: int
    account_login: Optional[int]
    terminal_connected: bool
    received_at: datetime


@dataclass(frozen=True)
class AccountState:
    """A read model only -- this phase never derives a trading decision
    from account state, it only reports and stores it."""

    schema_version: int
    magic_number: int
    balance: float
    equity: float
    margin: Optional[float]
    free_margin: Optional[float]
    currency: str
    leverage: Optional[int]
    received_at: datetime


@dataclass(frozen=True)
class PositionReport:
    schema_version: int
    position_id: str
    symbol: str
    direction: PositionDirection
    volume: float
    open_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    unrealized_pnl: Optional[float]
    magic_number: int
    received_at: datetime


@dataclass(frozen=True)
class PendingOrderReport:
    """Read-only. This phase never places a pending/limit/stop order --
    only BUY/SELL market orders are in scope -- but it must be able to
    report any pending orders that exist on the account."""

    schema_version: int
    order_id: str
    symbol: str
    order_type: str
    volume: float
    price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    magic_number: int
    received_at: datetime


@dataclass(frozen=True)
class TradeCommand:
    """One command relayed to the EA. `symbol`/`volume` apply to BUY/SELL;
    `position_id` applies to MODIFY_SL/MODIFY_TP/CLOSE/PARTIAL_CLOSE;
    `stop_loss` applies to BUY/SELL/MODIFY_SL; `take_profit` applies to
    BUY/SELL/MODIFY_TP; `close_volume` applies to PARTIAL_CLOSE only.
    Each field is `None` when the corresponding `CommandKind` does not
    use it -- never a placeholder value standing in for "not
    applicable"."""

    schema_version: int
    correlation_id: str
    command_kind: CommandKind
    symbol: Optional[str]
    volume: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_id: Optional[str]
    close_volume: Optional[float]
    magic_number: int
    max_slippage_points: int
    issued_at: datetime


@dataclass(frozen=True)
class ExecutionReport:
    """The EA's report of what happened when it executed one
    `TradeCommand` -- correlated by `correlation_id` only."""

    schema_version: int
    correlation_id: str
    magic_number: int
    success: bool
    broker_ticket: Optional[str]
    filled_price: Optional[float]
    filled_volume: Optional[float]
    error_code: Optional[str]
    reported_at: datetime


@dataclass(frozen=True)
class TradeTransactionReport:
    """An independent mirror of MT5's own native trade-transaction
    event, reported by the EA's `OnTradeTransaction` handler -- keyed by
    broker ticket, never by `correlation_id`. This exists purely as a
    drift-detection cross-check against `ExecutionReport`; it is never
    treated as more authoritative than a validated command's own
    reported result, and it never alters anything."""

    schema_version: int
    magic_number: int
    symbol: Optional[str]
    deal_ticket: Optional[str]
    order_ticket: Optional[str]
    transaction_type: str
    volume: Optional[float]
    price: Optional[float]
    reported_at: datetime


@dataclass(frozen=True)
class ErrorReport:
    schema_version: int
    magic_number: int
    error_code: str
    message: str
    context: Optional[str]
    reported_at: datetime


@dataclass(frozen=True)
class RawBarMessage:
    """One EA-reported price bar (Amendment 1, ADR-023). A transport-
    layer record only -- maps 1:1 onto
    `market_data_ingestion.models.RawBar`, which alone validates/
    normalizes it. `timeframe` is the plain string value
    (`market_data_ingestion.models.Timeframe`'s `.value`, e.g. "M15"),
    never re-typed as an enum here to avoid a second definition of the
    same concept. `broker_timestamp`/`source_timestamp` are two
    independent clock readings the EA takes at capture time (MT5's
    `TimeCurrent()`/`TimeLocal()`) -- `market_data_ingestion.validation`
    compares them for clock skew, never against Bridge's own wall
    clock."""

    schema_version: int
    symbol: str
    timeframe: str
    broker_timestamp: datetime
    source_timestamp: datetime
    bar_open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool
    sequence_number: int
    bid: Optional[float]
    ask: Optional[float]
    magic_number: int
    received_at: datetime


@dataclass(frozen=True)
class RawTickMessage:
    """One EA-reported tick (Amendment 1, ADR-023) -- maps 1:1 onto
    `market_data_ingestion.models.TickEvent`."""

    schema_version: int
    symbol: str
    bid: float
    ask: float
    magic_number: int
    received_at: datetime


@dataclass(frozen=True)
class EmergencyStopState:
    """`active=True` halts all new command issuance and is surfaced to
    the EA on its next poll so it can fail closed even if it never
    misses a heartbeat. This is the transport-level halt for this
    component only -- it is not the future Risk Engine's trading-
    decision kill-switch, nor the future Watchdog's infrastructure
    emergency stop; those are separate authorities in later phases."""

    active: bool
    reason: Optional[str]
    activated_at: Optional[datetime]


__all__ = [
    "SCHEMA_VERSION",
    "CommandKind",
    "PositionDirection",
    "ErrorCode",
    "HeartbeatMessage",
    "AccountState",
    "PositionReport",
    "PendingOrderReport",
    "TradeCommand",
    "ExecutionReport",
    "TradeTransactionReport",
    "ErrorReport",
    "EmergencyStopState",
    "RawBarMessage",
    "RawTickMessage",
]
