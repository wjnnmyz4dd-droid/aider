"""Production Deployment & Operations Infrastructure (Phase 5).

**Not a 15th pipeline stage, and no new ADR.** Exactly like
`orchestrator.py` (Phase 2), the real adapters (Phase 3), and
`paper_trading` (Phase 4), this package is operational tooling built
*around* the already-Accepted, already-implemented 13-package pipeline —
never a new decision authority, never a change to any existing engine's
logic. It exists one layer further out than any of those: VPS/process
supervision (start/stop/restart/monitor/backup the whole deployed stack),
not trading-pipeline integration.

See `docs/plans/phase5-production-deployment.md` for the full
research/plan record.
"""

from __future__ import annotations

from .backup_manager import BackupManager
from .config_manager import ConfigurationManager, ProfileConfig, REQUIRED_SECRET_KEYS
from .deployment_manager import ProductionDeploymentManager
from .deployment_validator import DeploymentValidator, REQUIRED_CHECK_NAMES
from .logging_manager import (
    JsonFormatter,
    archive_daily_logs,
    configure_production_logging,
    enforce_retention_policy,
    generate_crash_dump,
)
from .models import (
    SCHEMA_VERSION,
    BackupManifest,
    BackupRecord,
    BackupTarget,
    ConfigValidationIssue,
    ConfigValidationResult,
    DeploymentCheckResult,
    DeploymentProfile,
    DeploymentReadinessReport,
    MonitoringSnapshot,
    ResourceSample,
    RestartReason,
    RestartRecord,
    RestoreResult,
    ServiceDefinition,
    ServiceState,
    ServiceStatus,
    ShutdownResult,
    StartupResult,
)
from .monitoring import (
    MonitoringThresholds,
    ProductionMonitoring,
    default_cpu_sampler,
    default_disk_sampler,
    default_memory_sampler,
    default_network_latency_sampler,
    default_python_process_health_checker,
)
from .service_manager import MT5_SERVICE_NAME, WindowsServiceManager

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
    "ConfigurationManager",
    "ProfileConfig",
    "REQUIRED_SECRET_KEYS",
    "WindowsServiceManager",
    "MT5_SERVICE_NAME",
    "ProductionDeploymentManager",
    "JsonFormatter",
    "configure_production_logging",
    "archive_daily_logs",
    "generate_crash_dump",
    "enforce_retention_policy",
    "ProductionMonitoring",
    "MonitoringThresholds",
    "default_cpu_sampler",
    "default_memory_sampler",
    "default_disk_sampler",
    "default_network_latency_sampler",
    "default_python_process_health_checker",
    "BackupManager",
    "DeploymentValidator",
    "REQUIRED_CHECK_NAMES",
]
