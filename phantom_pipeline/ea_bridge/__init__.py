"""Hybrid MT5 MQL5 EA Bridge (`ADR-023`).

**Not a pipeline stage.** `phantom_pipeline/ea_bridge/` is a transport
package sitting behind the already-Accepted `mt5_bridge` stage —
`EABrokerAdapter` implements `mt5_bridge.broker_adapter.BrokerAdapter`'s
existing ABC exactly, so `MT5Bridge` needs zero code change to use it
instead of `MT5Adapter`/`FakeBrokerAdapter`. It holds no decision,
execution, risk, compliance, or scoring authority (`ADR-023` Hard Rules
1-4) — the only commands it ever relays are ones `mt5_bridge` already
approved.

See `docs/adr/ADR-023-mql5-ea-bridge.md` and
`docs/plans/mql5-ea-bridge.md` for the full research/plan record, and
`MT5_EA_BRIDGE_GUIDE.md` for the deployment guide.
"""

from __future__ import annotations

from .broker_adapter import EABrokerAdapter, command_from_broker_request
from .command_queue import CommandQueue
from .config import EA_BRIDGE_VERSION, EABridgeConfig
from .engine import EABridgeEngine
from .http_server import make_handler, registered_routes, serve
from .logging_sink import (
    log_account_state,
    log_emergency_stop,
    log_error_report,
    log_execution_report,
    log_heartbeat,
    log_position_report,
    log_tick,
)
from .metrics import EABridgeMetrics
from .models import (
    SCHEMA_VERSION,
    BarMessage,
    EAAccountState,
    EmergencyStopState,
    ErrorReport,
    ExecutionCommand,
    ExecutionReport,
    HeartbeatMessage,
    PositionReport,
    TickMessage,
)

__all__ = [
    "SCHEMA_VERSION",
    "EA_BRIDGE_VERSION",
    "EABridgeConfig",
    "HeartbeatMessage",
    "EAAccountState",
    "TickMessage",
    "BarMessage",
    "PositionReport",
    "ExecutionCommand",
    "ExecutionReport",
    "ErrorReport",
    "EmergencyStopState",
    "CommandQueue",
    "EABrokerAdapter",
    "command_from_broker_request",
    "EABridgeEngine",
    "EABridgeMetrics",
    "make_handler",
    "serve",
    "registered_routes",
    "log_heartbeat",
    "log_account_state",
    "log_tick",
    "log_position_report",
    "log_execution_report",
    "log_error_report",
    "log_emergency_stop",
]
