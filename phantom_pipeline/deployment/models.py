"""Shared, side-effect-free types for the Deployment package (Phase 5).

Every type here is a plain record produced by one of this package's
modules — no logic lives in this file, matching every other package's own
`models.py` convention (`ADR-002` through `ADR-013`'s own precedent).
Nothing here represents a trading instruction or touches any pipeline
stage's own decision objects; this package sits entirely outside the
`ADR-001` trading chain (VPS/process supervision, not a pipeline stage).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Tuple

SCHEMA_VERSION = 1


class ServiceState(Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    CRASHED = "CRASHED"
    STOPPING = "STOPPING"


class DeploymentProfile(Enum):
    DEV = "DEV"
    PAPER = "PAPER"
    LIVE = "LIVE"


class RestartReason(Enum):
    CRASH_DETECTED = "CRASH_DETECTED"
    HANG_DETECTED = "HANG_DETECTED"
    MANUAL = "MANUAL"


class BackupTarget(Enum):
    CONFIGURATION = "CONFIGURATION"
    DATABASE = "DATABASE"
    ANALYTICS = "ANALYTICS"
    TRADE_HISTORY = "TRADE_HISTORY"


@dataclass(frozen=True)
class ServiceDefinition:
    """One managed service, wired up by whoever assembles the deployment
    (the one place that legitimately holds every real start/stop/health
    callable) — mirrors `RealRecoveryActionExecutor`'s own
    dependency-injection shape so every OS-touching action stays testable
    on a non-Windows CI host."""

    name: str
    start: Callable[[], bool]
    stop: Callable[[], bool]
    health_check: Callable[[], bool]
    depends_on: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    state: ServiceState
    detail: str
    timestamp: datetime


@dataclass(frozen=True)
class StartupResult:
    statuses: Tuple[ServiceStatus, ...]
    all_started: bool
    aborted_reason: Optional[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "statuses", tuple(self.statuses))


@dataclass(frozen=True)
class ShutdownResult:
    statuses: Tuple[ServiceStatus, ...]
    all_stopped: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "statuses", tuple(self.statuses))


@dataclass(frozen=True)
class RestartRecord:
    component: str
    reason: RestartReason
    detail: str
    timestamp: datetime
    succeeded: bool


@dataclass(frozen=True)
class ConfigValidationIssue:
    field: str
    message: str
    is_error: bool  # True = blocks startup; False = warning only


@dataclass(frozen=True)
class ConfigValidationResult:
    profile: DeploymentProfile
    issues: Tuple[ConfigValidationIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def valid(self) -> bool:
        return not any(issue.is_error for issue in self.issues)


@dataclass(frozen=True)
class ResourceSample:
    cpu_percent: Optional[float]
    memory_percent: Optional[float]
    disk_percent: Optional[float]
    network_latency_ms: Optional[float]
    timestamp: datetime


@dataclass(frozen=True)
class MonitoringSnapshot:
    resource: ResourceSample
    mt5_connection_healthy: Optional[bool]
    python_process_healthy: Optional[bool]
    dashboard_healthy: Optional[bool]
    timestamp: datetime


@dataclass(frozen=True)
class BackupRecord:
    target: BackupTarget
    source_path: str
    backup_path: str
    checksum: str
    size_bytes: int
    timestamp: datetime


@dataclass(frozen=True)
class BackupManifest:
    records: Tuple[BackupRecord, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))


@dataclass(frozen=True)
class RestoreResult:
    target: BackupTarget
    restored: bool
    detail: str
    timestamp: datetime


@dataclass(frozen=True)
class DeploymentCheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DeploymentReadinessReport:
    profile: DeploymentProfile
    checks: Tuple[DeploymentCheckResult, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))

    @property
    def all_passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def blockers(self) -> Tuple[str, ...]:
        return tuple(check.name for check in self.checks if not check.passed)


__all__ = [
    "SCHEMA_VERSION",
    "ServiceState",
    "DeploymentProfile",
    "RestartReason",
    "BackupTarget",
    "ServiceDefinition",
    "ServiceStatus",
    "StartupResult",
    "ShutdownResult",
    "RestartRecord",
    "ConfigValidationIssue",
    "ConfigValidationResult",
    "ResourceSample",
    "MonitoringSnapshot",
    "BackupRecord",
    "BackupManifest",
    "RestoreResult",
    "DeploymentCheckResult",
    "DeploymentReadinessReport",
]
