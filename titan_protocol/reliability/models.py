"""Data models for the System Reliability Engine (Phase 3B, ADR-032).

Every type here is a plain observation record or a derived health
judgment. Nothing here can hold a trade instruction, a strategy
selection, or a compliance decision (ADR-032 Hard Rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from titan_protocol.runtime.models import CycleOutcome

SCHEMA_VERSION = 1


class HealthState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class DegradationLevel(Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    HALTED = "HALTED"


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    state: HealthState
    last_heartbeat_at: Optional[datetime]
    reason: str


@dataclass(frozen=True)
class ResourceUsage:
    cpu_percent: Optional[float]
    memory_percent: Optional[float]
    sampled_at: datetime


@dataclass(frozen=True)
class QueueDepth:
    name: str
    depth: int
    reported_at: datetime


@dataclass(frozen=True)
class CycleOutcomeStats:
    pair: str
    total_cycles: int
    failed_cycles: int
    average_duration_ms: float
    last_outcome: Optional[CycleOutcome]
    last_seen_at: Optional[datetime]


@dataclass(frozen=True)
class SystemHealthSnapshot:
    generated_at: datetime
    degradation_level: DegradationLevel
    component_health: Tuple[ComponentHealth, ...]
    resource_usage: Optional[ResourceUsage]
    queue_depths: Tuple[QueueDepth, ...]
    cycle_stats: Tuple[CycleOutcomeStats, ...]
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class RecoveryOutcome:
    component: str
    attempted: bool
    succeeded: bool
    reason: str
    timestamp: datetime


__all__ = [
    "SCHEMA_VERSION",
    "HealthState",
    "DegradationLevel",
    "ComponentHealth",
    "ResourceUsage",
    "QueueDepth",
    "CycleOutcomeStats",
    "SystemHealthSnapshot",
    "RecoveryOutcome",
]
