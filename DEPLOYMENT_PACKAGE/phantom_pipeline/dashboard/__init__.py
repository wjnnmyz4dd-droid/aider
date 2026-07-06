"""The Dashboard package (ADR-012) — Phase 1.

A read-only operational interface with no direct connection to any
pipeline stage (Pipeline position). Its only two data sources are a
Prometheus read port (standing in for every stage's + Watchdog's
already-exported health/metrics, `ADR-002` through `ADR-011`) and
Analytics' read-only models (`ADR-010` §5) — no other stage's package is
imported here. `DashboardEngine.build_*_view()` renders one of the ten
views (§5); every one is a pure read, never a write, never a
recomputation of a value Prometheus or Analytics already produced.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, DASHBOARD_VERSION, DashboardConfig
from .engine import DashboardEngine
from .metrics import DashboardMetrics
from .models import SCHEMA_VERSION, AlertView, ComponentStatus, SystemMetric, View, ViewName
from .prometheus_port import FakePrometheusReadPort, PrometheusReadPort

__all__ = [
    "DEFAULT_CONFIG",
    "DASHBOARD_VERSION",
    "DashboardConfig",
    "DashboardEngine",
    "DashboardMetrics",
    "SCHEMA_VERSION",
    "AlertView",
    "ComponentStatus",
    "SystemMetric",
    "View",
    "ViewName",
    "FakePrometheusReadPort",
    "PrometheusReadPort",
]
