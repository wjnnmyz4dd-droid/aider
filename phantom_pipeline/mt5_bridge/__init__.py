"""MT5 Bridge package (ADR-008, Amendment 1) — Phase 1.

Consumes only `ExecutionDecision` (ADR-007, must be APPROVE), the
originating `RiskDecision` (ADR-005), `ComplianceDecision` (ADR-006), and
`CandidateTrade` (ADR-003) — all read-only — plus `PositionAdjustmentRequest`/
`PositionCloseRequest` (ADR-009 §5, accepted only from Position Manager).
Never generates, approves, or blocks a trade; never recalculates sizing,
SL/TP, scores, risk, or compliance; never modifies any upstream object.
Produces `BrokerRequest`, `BrokerAcknowledgement`, `ExecutionReceipt`,
`BrokerError`, `FillReport`, `ConnectionStatus`, `SynchronizationStatus` —
one record per event, never discarded (ADR-008 §2, §3, §5).
"""

from __future__ import annotations

from .broker_adapter import BrokerAdapter, FakeBrokerAdapter
from .config import DEFAULT_CONFIG, MT5_BRIDGE_VERSION, MT5BridgeConfig
from .engine import MT5Bridge
from .execution_id import make_execution_id
from .idempotency_store import InMemoryTransportIdempotencyStore, TransportIdempotencyStore
from .metrics import MT5BridgeMetrics
from .models import (
    SCHEMA_VERSION,
    BrokerAcknowledgement,
    BrokerError,
    BrokerRequest,
    ConnectionState,
    ConnectionStatus,
    ExecutionReceipt,
    FillReport,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    RequestKind,
    SynchronizationStatus,
)

__all__ = [
    "BrokerAdapter",
    "FakeBrokerAdapter",
    "DEFAULT_CONFIG",
    "MT5_BRIDGE_VERSION",
    "MT5BridgeConfig",
    "MT5Bridge",
    "make_execution_id",
    "InMemoryTransportIdempotencyStore",
    "TransportIdempotencyStore",
    "MT5BridgeMetrics",
    "SCHEMA_VERSION",
    "BrokerAcknowledgement",
    "BrokerError",
    "BrokerRequest",
    "ConnectionState",
    "ConnectionStatus",
    "ExecutionReceipt",
    "FillReport",
    "PositionAdjustmentRequest",
    "PositionCloseRequest",
    "RequestKind",
    "SynchronizationStatus",
]
