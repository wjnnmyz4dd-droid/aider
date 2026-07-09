"""PhantomBridgeEA execution authority (Phase 1).

The single execution authority for Phantom: MT5 connection, trade
execution, position management, and the EA<->Python communication
transport. Holds no trading-decision authority of any kind -- it only
ever relays a `TradeCommand` supplied to it via `BridgeEngine.submit_command()`,
validates it, and reports back what actually happened. Later phases
(scanner, strategy, risk, intelligence, watchdog, config) are the ones
that will decide *whether* and *what* to trade; this package only ever
executes.
"""

from __future__ import annotations

from .command_queue import CommandQueue
from .config import BRIDGE_VERSION, BridgeConfig
from .connection_health import ConnectionHealth
from .engine import BridgeEngine
from .logging_sink import (
    log_account_state,
    log_command_delivered,
    log_command_submitted,
    log_emergency_stop,
    log_error_report,
    log_execution_report,
    log_heartbeat,
    log_pending_orders,
    log_positions,
    log_trade_transaction,
)
from .metrics import BridgeMetrics
from .models import (
    SCHEMA_VERSION,
    AccountState,
    CommandKind,
    EmergencyStopState,
    ErrorCode,
    ErrorReport,
    ExecutionReport,
    HeartbeatMessage,
    PendingOrderReport,
    PositionDirection,
    PositionReport,
    TradeCommand,
    TradeTransactionReport,
)
from .server import make_handler, registered_routes, serve

__all__ = [
    "SCHEMA_VERSION",
    "BRIDGE_VERSION",
    "BridgeConfig",
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
    "CommandQueue",
    "ConnectionHealth",
    "BridgeEngine",
    "BridgeMetrics",
    "make_handler",
    "serve",
    "registered_routes",
    "log_heartbeat",
    "log_account_state",
    "log_positions",
    "log_pending_orders",
    "log_command_submitted",
    "log_command_delivered",
    "log_execution_report",
    "log_trade_transaction",
    "log_error_report",
    "log_emergency_stop",
]
