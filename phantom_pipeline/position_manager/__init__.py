"""Position Manager package (ADR-009) — Phase 1.

Manages an already-open position's lifecycle only — begins after MT5
Bridge confirms a fill (`ExecutionReceipt`/`FillReport`, ADR-008 §5) and
never creates trades, never modifies any upstream immutable decision,
and never talks to MT5 directly. Every management action is expressed
as `PositionAdjustmentRequest`/`PositionCloseRequest`, routed back
through MT5 Bridge for actual submission (ADR-009 §2, §9). Produces
`PositionManagementDecision` (one per evaluation, always) and
`PositionUpdate`; resolves `SynchronizationStatus` discrepancies into
`PositionSynchronizationResult` (ADR-009 §5, §8).
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, POSITION_MANAGER_VERSION, PositionManagerConfig
from .engine import PositionManager
from .execution_id import make_position_execution_id
from .metrics import PositionManagerMetrics
from .models import (
    SCHEMA_VERSION,
    LifecycleState,
    LivePositionState,
    ManagementAction,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    PositionManagementDecision,
    PositionSynchronizationResult,
    PositionUpdate,
    RuleEvaluation,
    RuleStatus,
)
from .state_store import InMemoryPositionManagerStateStore, PositionManagerStateStore

__all__ = [
    "DEFAULT_CONFIG",
    "POSITION_MANAGER_VERSION",
    "PositionManagerConfig",
    "PositionManager",
    "make_position_execution_id",
    "PositionManagerMetrics",
    "SCHEMA_VERSION",
    "LifecycleState",
    "LivePositionState",
    "ManagementAction",
    "PositionAdjustmentRequest",
    "PositionCloseRequest",
    "PositionManagementDecision",
    "PositionSynchronizationResult",
    "PositionUpdate",
    "RuleEvaluation",
    "RuleStatus",
    "InMemoryPositionManagerStateStore",
    "PositionManagerStateStore",
]
