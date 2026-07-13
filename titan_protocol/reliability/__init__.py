"""System Reliability Engine (Phase 3B).

Watches every other component's health and provides the fail-closed
signal every live component's caller should check before proceeding.
It never trades, sizes, selects a strategy, or makes a compliance
decision -- it only observes, measures, and, within a narrow,
pre-approved set of actions, recovers. See
`docs/adr/ADR-032-system-reliability-engine.md`.
"""

from __future__ import annotations

from .config import RELIABILITY_ENGINE_VERSION, ReliabilityConfig
from .degradation import derive_degradation_level
from .engine import ReliabilityEngine
from .heartbeat import HeartbeatStore, derive_heartbeat_state
from .logging_sink import log_health_snapshot
from .metrics import ReliabilityMetrics
from .models import (
    SCHEMA_VERSION,
    ComponentHealth,
    CycleOutcomeStats,
    DegradationLevel,
    HealthState,
    QueueDepth,
    RecoveryOutcome,
    ResourceUsage,
    SystemHealthSnapshot,
)
from .recovery import attempt_recovery
from .resource_monitor import (
    CpuSampler,
    MemorySampler,
    default_cpu_sampler,
    default_memory_sampler,
    sample_resource_usage,
)
from .snapshot_freshness import is_snapshot_fresh

__all__ = [
    "RELIABILITY_ENGINE_VERSION",
    "SCHEMA_VERSION",
    "ReliabilityConfig",
    "ReliabilityEngine",
    "ReliabilityMetrics",
    "HealthState",
    "DegradationLevel",
    "ComponentHealth",
    "ResourceUsage",
    "QueueDepth",
    "CycleOutcomeStats",
    "SystemHealthSnapshot",
    "RecoveryOutcome",
    "HeartbeatStore",
    "derive_heartbeat_state",
    "derive_degradation_level",
    "is_snapshot_fresh",
    "attempt_recovery",
    "CpuSampler",
    "MemorySampler",
    "default_cpu_sampler",
    "default_memory_sampler",
    "sample_resource_usage",
    "log_health_snapshot",
]
