"""The Watchdog package (ADR-011) — Phase 1.

A cross-cutting operational service, not a pipeline stage — it observes
every stage (Market Data through Analytics) and reports/recovers
infrastructure only; it never makes a trading decision (Hard Rules,
`ADR-011`). Zero imports from any other `phantom_pipeline` subpackage —
every input to `WatchdogEngine` is a plain, caller-supplied value.

`WatchdogEngine.evaluate()` produces one `SystemHealth` snapshot per call,
evaluating every supplied `ComponentSignal` independently with no
short-circuit. `WatchdogEngine.attempt_recovery()` is a separate,
explicitly-invoked call scoped to the 8 named, bounded infrastructure
actions in `RecoveryActionType` (ADR-011 §7); `WatchdogEngine.
generate_alerts()` classifies a `SystemHealth` snapshot into `Alert`s
(ADR-011 §11).
"""

from __future__ import annotations

from .alerting import classify_alert, resolve_repeat_count, should_escalate
from .checks import aggregate_overall_health, derive_component_health, derive_heartbeat_status, is_recovery_eligible
from .config import DEFAULT_CONFIG, WATCHDOG_VERSION, WatchdogConfig
from .engine import WatchdogEngine
from .metrics import WatchdogMetrics
from .models import (
    SCHEMA_VERSION,
    Alert,
    AlertClass,
    ComponentHealth,
    ComponentKind,
    ComponentSignal,
    HealthState,
    HeartbeatStatus,
    RecoveryActionType,
    RecoveryOutcome,
    RecoveryStatus,
    SystemHealth,
)
from .recovery_executor import FakeRecoveryActionExecutor, RecoveryActionExecutor
from .state_store import InMemoryWatchdogStateStore, WatchdogStateStore
from .trace import make_health_trace_id

__all__ = [
    "classify_alert",
    "resolve_repeat_count",
    "should_escalate",
    "aggregate_overall_health",
    "derive_component_health",
    "derive_heartbeat_status",
    "is_recovery_eligible",
    "DEFAULT_CONFIG",
    "WATCHDOG_VERSION",
    "WatchdogConfig",
    "WatchdogEngine",
    "WatchdogMetrics",
    "SCHEMA_VERSION",
    "Alert",
    "AlertClass",
    "ComponentHealth",
    "ComponentKind",
    "ComponentSignal",
    "HealthState",
    "HeartbeatStatus",
    "RecoveryActionType",
    "RecoveryOutcome",
    "RecoveryStatus",
    "SystemHealth",
    "FakeRecoveryActionExecutor",
    "RecoveryActionExecutor",
    "InMemoryWatchdogStateStore",
    "WatchdogStateStore",
    "make_health_trace_id",
]
