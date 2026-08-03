"""Dashboard read-only display objects (ADR-012 §2, §5, §7, §8).

**These are not pipeline objects.** Per `INTERFACE_SPECIFICATION.md` §2,
the Dashboard produces "no new output objects — a pure read/visualization
layer" — nothing downstream consumes any type in this module; they exist
only so this package's pure view-builder functions have a concrete,
testable return shape for a human viewer. None of them are part of the
trading `trace_id` chain or the Watchdog health-event chain in the sense
of *originating* one — each merely carries forward whichever `trace_id`
its source object already had (§7), never inventing or merging one.

Every field here is exactly what Prometheus or Analytics already computed
(§8) — no aggregation, no recomputation, presentation-layer formatting
only (e.g. `ViewName`, tuple grouping).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..analytics.models import PerformanceStatistics, TradeProvenanceRecord

SCHEMA_VERSION = 1


class ViewName(Enum):
    """The exhaustive ten views (ADR-012 §5)."""

    OVERVIEW = "OVERVIEW"
    TRADING = "TRADING"
    RISK = "RISK"
    COMPLIANCE = "COMPLIANCE"
    EXECUTION = "EXECUTION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    ANALYTICS = "ANALYTICS"
    ALERTS = "ALERTS"
    RESEARCH = "RESEARCH"
    AUDIT = "AUDIT"


@dataclass(frozen=True)
class ComponentStatus:
    """One component's health, exactly as already reported by Prometheus
    (`ADR-011` §13's export) — `health_state` is carried as a plain
    string (whatever label the source stage's own metrics already used),
    never re-interpreted through a Dashboard-owned enum, so the Dashboard
    never becomes a second authority on what a health value means (§8)."""

    component: str
    health_state: str
    reason: str
    trace_id: str
    timestamp: datetime


@dataclass(frozen=True)
class AlertView:
    """A read-only mirror of one of Watchdog's currently-reported alerts
    (`ADR-011` §11, via Prometheus) — display-only; no acknowledgement,
    suppression, or routing capability exists anywhere on this type or
    any method that consumes it (§6)."""

    component: str
    alert_class: str
    severity: str
    detail: str
    repeat_count: int
    trace_id: str
    timestamp: datetime


@dataclass(frozen=True)
class SystemMetric:
    """One system-level metric exactly as Prometheus/Watchdog already
    computed it (§8) — Recovery Time, Availability, CPU, RAM, Disk,
    Network, Latency, etc."""

    name: str
    value: float
    unit: str
    timestamp: datetime


@dataclass(frozen=True)
class View:
    """One rendered view (ADR-012 §5) — a read-only bundle of whatever
    subset of §4's two sources that view displays. Immutable once built;
    every item inside it is traceable (§7) via its own `trace_id`/
    `timestamp`/`component`/`status`, never a single view-level `trace_id`
    that would blur the trading chain and the health-event chain
    together."""

    schema_version: int
    view_name: ViewName
    generated_at: datetime
    component_statuses: Tuple[ComponentStatus, ...]
    system_metrics: Tuple[SystemMetric, ...]
    alerts: Tuple[AlertView, ...]
    trade_records: Tuple[TradeProvenanceRecord, ...]
    performance: Optional[PerformanceStatistics]

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_statuses", tuple(self.component_statuses))
        object.__setattr__(self, "system_metrics", tuple(self.system_metrics))
        object.__setattr__(self, "alerts", tuple(self.alerts))
        object.__setattr__(self, "trade_records", tuple(self.trade_records))
