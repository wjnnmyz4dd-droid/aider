"""Watchdog input/output objects (ADR-011 §5, §6, §7).

The Watchdog is not a pipeline stage (ADR-011 "Pipeline position") — it
has no `trace_id`-chained position between two adjacent trading stages
the way Scanner through Analytics do. Its own `trace_id` (carried on
`SystemHealth`/`Alert`) identifies a **separate health-event chain**,
never to be confused with the trading `trace_id` chain established at
Scanner (`ADR-002` §8) onward, per this ADR's own §5 and
`INTERFACE_SPECIFICATION.md`'s "Universal properties" section.

Every object here is structurally incapable of holding a trading
instruction or a modified trading-decision field (ADR-011 §5's Forbidden
list, Hard Rules) — no field anywhere below can represent a
`CandidateTrade`, `ScoreResult`, `RiskDecision`, `ComplianceDecision`,
`ExecutionDecision`, or `PositionManagementDecision`.

This module has zero imports from any other `phantom_pipeline`
subpackage (explicit, user-confirmed constraint) — every enum/type here
is defined fresh, even where a same-named concept exists elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

SCHEMA_VERSION = 1


class HealthState(Enum):
    """The exhaustive health-state vocabulary (ADR-011 §6)."""

    UNKNOWN = "UNKNOWN"
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    RECOVERING = "RECOVERING"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"
    SHUTDOWN = "SHUTDOWN"


# Severity ladder (ADR-011 §6): HEALTHY -> DEGRADED -> WARNING ->
# RECOVERING -> CRITICAL -> OFFLINE. UNKNOWN is "at least as severe as
# CRITICAL" (tied with CRITICAL's rank here — aggregation only needs the
# worst rank, never which of two equally-severe states "wins"). STARTING
# and SHUTDOWN are lifecycle-phase states, deliberately excluded from
# this ladder (§6) — they are never combined by severity rank.
SEVERITY_RANK = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.WARNING: 2,
    HealthState.RECOVERING: 3,
    HealthState.CRITICAL: 4,
    HealthState.UNKNOWN: 4,
    HealthState.OFFLINE: 5,
}

LIFECYCLE_STATES = (HealthState.STARTING, HealthState.SHUTDOWN)


class ComponentKind(Enum):
    """The four monitored categories (ADR-011 §2)."""

    PIPELINE_STAGE = "PIPELINE_STAGE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    OPERATIONAL_SURFACE = "OPERATIONAL_SURFACE"


class RecoveryActionType(Enum):
    """The exhaustive, bounded recovery-action vocabulary (ADR-011 §7) —
    each one a bounded infrastructure action, never a decision action.
    No autonomous logic anywhere in this package invents a recovery
    action outside this list."""

    RESTART_SERVICE = "RESTART_SERVICE"
    RESTART_WORKER = "RESTART_WORKER"
    RECONNECT_DEPENDENCY = "RECONNECT_DEPENDENCY"
    REBUILD_CONNECTION = "REBUILD_CONNECTION"
    CLEAR_STALE_HEARTBEAT = "CLEAR_STALE_HEARTBEAT"
    RESTART_MONITORING = "RESTART_MONITORING"
    ROTATE_LOGS = "ROTATE_LOGS"
    RELOAD_CONFIGURATION = "RELOAD_CONFIGURATION"


class RecoveryOutcome(Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AlertClass(Enum):
    """The alert classification vocabulary (ADR-011 §11)."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    RECOVERY = "RECOVERY"
    ESCALATION = "ESCALATION"


@dataclass(frozen=True)
class ComponentSignal:
    """Caller-supplied facts about one monitored component for a single
    `evaluate()` call (ADR-011 §2) — plain values only, never an object
    imported from the stage being observed (the zero-cross-package-import
    constraint applies to this package's own code, not to what a caller
    elsewhere chooses to pass in as a plain string/enum/bool).

    `reported_state` is that stage's own already-computed state where one
    exists (e.g. MT5 Bridge's `ConnectionStatus`, Position Manager's
    `PositionSynchronizationResult`) translated by the caller into a
    `HealthState` — the Watchdog "observes and surfaces," it never
    recomputes or reissues (§5)."""

    component: str
    kind: ComponentKind
    reported_state: Optional[HealthState] = None
    detail: str = ""


@dataclass(frozen=True)
class ComponentHealth:
    """One component's derived health for a single `SystemHealth`
    snapshot (ADR-011 §5) — immutable once produced."""

    component: str
    kind: ComponentKind
    state: HealthState
    reason: str
    timestamp: datetime


@dataclass(frozen=True)
class HeartbeatStatus:
    """One component's heartbeat status (ADR-011 §9). `expired` means the
    most recent heartbeat is older than its configured maximum age —
    treated as "no heartbeat received," never as stale-but-valid."""

    component: str
    last_seen_at: Optional[datetime]
    missed_count: int
    expired: bool
    timestamp: datetime


@dataclass(frozen=True)
class RecoveryStatus:
    """One component's recovery status (ADR-011 §5, §7, §8). `frozen`
    means further automatic recovery is suspended for this component
    until a human clears it or a fresh, unambiguously-healthy signal is
    observed directly (§8) — never induced by the Watchdog's own action."""

    component: str
    in_progress: bool
    frozen: bool
    last_action: Optional[RecoveryActionType]
    last_outcome: Optional[RecoveryOutcome]
    attempts_in_window: int
    timestamp: datetime


@dataclass(frozen=True)
class SystemHealth:
    """The Watchdog's single output object (ADR-011 §5). Immutable once
    produced — a point-in-time snapshot, superseded by the next one, never
    rewritten in place.

    `overall_health` is always the worst (most severe) state across every
    monitored component — never an average or a majority vote (§5).
    `trace_id` identifies this ADR's own health-event chain, distinct
    from the trading `trace_id` chain (§5).

    Structurally incapable of holding a trading instruction or a modified
    trading-decision field — no such field is declared anywhere on this
    type (§5's type-level guarantee)."""

    schema_version: int
    trace_id: str
    overall_health: HealthState
    component_health: Tuple[ComponentHealth, ...]
    heartbeat_statuses: Tuple[HeartbeatStatus, ...]
    recovery_statuses: Tuple[RecoveryStatus, ...]
    timestamp: datetime
    system_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_health", tuple(self.component_health))
        object.__setattr__(self, "heartbeat_statuses", tuple(self.heartbeat_statuses))
        object.__setattr__(self, "recovery_statuses", tuple(self.recovery_statuses))


@dataclass(frozen=True)
class Alert:
    """One alert (ADR-011 §11) — outbound-notify-only content; never an
    inbound control surface and never a trading instruction. Repeated
    identical alerts within a configured window collapse into one alert
    with `repeat_count` incremented, rather than resending individually."""

    schema_version: int
    trace_id: str
    component: str
    alert_class: AlertClass
    severity: HealthState
    detail: str
    repeat_count: int
    timestamp: datetime
