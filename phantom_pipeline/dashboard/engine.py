"""The Dashboard (ADR-012).

`DashboardEngine` builds one of the ten views (§5) at a time — always a
pure read: it never recomputes a displayed value (§8), never writes to
Prometheus, Analytics, Watchdog, or any pipeline stage (Hard Rules), and
holds no operational-control capability of any kind.

Every `build_*_view` method is a pure function of (the Prometheus port's
already-exported data, explicitly caller-supplied Analytics records/
statistics, and `now`) — mirroring every prior stage's "explicit
caller-supplied parameter, no hidden state" discipline. The only
dependency this package imports from elsewhere in `phantom_pipeline` is
`analytics.models` (the one ADR-explicit direct connection, §4); every
other stage's data, including Watchdog's, arrives only through
`PrometheusReadPort`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ..analytics.models import PerformanceStatistics, TradeProvenanceRecord
from .config import DEFAULT_CONFIG, DashboardConfig
from .logging_sink import log_view_built
from .metrics import DashboardMetrics
from .models import SCHEMA_VERSION, View, ViewName
from .prometheus_port import PrometheusReadPort


class DashboardEngine:
    def __init__(
        self,
        prometheus: PrometheusReadPort,
        config: DashboardConfig = DEFAULT_CONFIG,
        metrics: Optional[DashboardMetrics] = None,
    ):
        self.prometheus = prometheus
        self.config = config
        self.metrics = metrics

    def _assemble(
        self,
        view_name: ViewName,
        now: datetime,
        components: Optional[Sequence[str]] = None,
        include_system_metrics: bool = False,
        include_alerts: bool = False,
        records: Sequence[TradeProvenanceRecord] = (),
        performance: Optional[PerformanceStatistics] = None,
    ) -> View:
        statuses = self.prometheus.component_statuses(components)
        system_metrics = self.prometheus.system_metrics() if include_system_metrics else ()
        alerts = self.prometheus.alerts() if include_alerts else ()
        view = View(
            schema_version=SCHEMA_VERSION,
            view_name=view_name,
            generated_at=now,
            component_statuses=statuses,
            system_metrics=system_metrics,
            alerts=alerts,
            trade_records=tuple(records),
            performance=performance,
        )
        log_view_built(view)
        if self.metrics is not None:
            self.metrics.record_view_built(view_name)
        return view

    def build_overview_view(
        self, now: datetime, performance: Optional[PerformanceStatistics] = None
    ) -> View:
        """Overall Health across every monitored component, plus a
        high-level performance summary (§5)."""
        return self._assemble(ViewName.OVERVIEW, now, components=None, include_system_metrics=True, performance=performance)

    def build_trading_view(self, now: datetime, records: Sequence[TradeProvenanceRecord] = ()) -> View:
        """Scanner/Strategy Engine/Scoring Engine health and trade flow (§5)."""
        return self._assemble(ViewName.TRADING, now, components=self.config.trading_components, records=records)

    def build_risk_view(
        self, now: datetime, performance: Optional[PerformanceStatistics] = None
    ) -> View:
        """Risk Engine health and risk-related aggregate statistics, as
        already recorded by Analytics — introduces no new risk
        computation (§5)."""
        return self._assemble(ViewName.RISK, now, components=self.config.risk_components, performance=performance)

    def build_compliance_view(self, now: datetime) -> View:
        """Compliance Engine health and current compliance state, as
        already reported — never a new evaluation (§5)."""
        return self._assemble(ViewName.COMPLIANCE, now, components=self.config.compliance_components)

    def build_execution_view(self, now: datetime) -> View:
        """Execution Validator and MT5 Bridge health (§5)."""
        return self._assemble(ViewName.EXECUTION, now, components=self.config.execution_components)

    def build_infrastructure_view(self, now: datetime) -> View:
        """CPU/RAM/Disk/Network/VPS/Watchdog health, from Prometheus (§5)."""
        return self._assemble(
            ViewName.INFRASTRUCTURE, now, components=self.config.infrastructure_components, include_system_metrics=True
        )

    def build_analytics_view(
        self,
        now: datetime,
        records: Sequence[TradeProvenanceRecord] = (),
        performance: Optional[PerformanceStatistics] = None,
    ) -> View:
        """The performance-statistics view proper (§5) — exactly what
        `ADR-010` §9 already computed, no Dashboard-side recomputation."""
        return self._assemble(ViewName.ANALYTICS, now, components=(), records=records, performance=performance)

    def build_alerts_view(self, now: datetime) -> View:
        """Display-only mirror of Watchdog's current alert state (§6) —
        no acknowledgement/suppression/routing capability anywhere on
        this view or the method that built it."""
        return self._assemble(ViewName.ALERTS, now, components=(), include_alerts=True)

    def build_research_view(self, now: datetime) -> View:
        """Read-only surface for `ADR-016`/`ADR-019` advisory output
        (§5). Both are `NOT STARTED` as of this Phase 1 — no upstream
        data source exists yet, so this view is structurally ready but
        empty; it never fabricates placeholder content."""
        return self._assemble(ViewName.RESEARCH, now, components=())

    def build_audit_view(self, now: datetime, records: Sequence[TradeProvenanceRecord] = ()) -> View:
        """Human-facing browsing of `ADR-010`'s `TradeProvenanceRecord`s
        (§5) — the human-facing counterpart to `ADR-010` §7's
        programmatic explainability."""
        return self._assemble(ViewName.AUDIT, now, components=(), records=records)
