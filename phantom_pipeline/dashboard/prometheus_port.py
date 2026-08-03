"""The Prometheus read boundary (ADR-012 §4, §9).

`PrometheusReadPort` is the sole abstraction through which the Dashboard
reaches every pipeline stage's and Watchdog's already-exported health/
metrics data (`ADR-002` through `ADR-011`, each independently required to
export additively) — "Pipeline stages allowed: none directly. [...] reads
only from Prometheus" (`ADR-011`/`ADR-015`'s Grafana section, generalized
here per §4). No dedicated Prometheus client exists anywhere in this
repository (no live metrics-scraping process is implemented) — mirroring
`mt5_bridge.broker_adapter.BrokerAdapter`'s own justification, Phase 1
ships `FakePrometheusReadPort`, a fully deterministic, in-memory test
double. A real port wrapping an actual Prometheus HTTP query API is
future work, not invented here.

**Structural read-only guarantee**: every abstract method on this
interface is a query (no arguments beyond an optional filter, no
mutation) — there is no `set_*`/`write_*`/`clear_*` method anywhere on
the ABC itself, only on the Fake test double, which exists solely to
script deterministic test data, not to represent a real write path
(§4, §9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional, Sequence, Tuple

from .models import AlertView, ComponentStatus, SystemMetric


class PrometheusReadPort(ABC):
    @abstractmethod
    def component_statuses(self, components: Optional[Sequence[str]] = None) -> Tuple[ComponentStatus, ...]:
        ...

    @abstractmethod
    def system_metrics(self) -> Tuple[SystemMetric, ...]:
        ...

    @abstractmethod
    def alerts(self) -> Tuple[AlertView, ...]:
        ...


class FakePrometheusReadPort(PrometheusReadPort):
    """A deterministic, fully scriptable in-memory Prometheus double for
    tests. Nothing here talks to any real network or process — every
    response is exactly what was scripted in advance via the setter
    methods below."""

    def __init__(self) -> None:
        self._component_statuses: Dict[str, ComponentStatus] = {}
        self._system_metrics: Dict[str, SystemMetric] = {}
        self._alerts: Tuple[AlertView, ...] = ()

    def set_component_status(self, status: ComponentStatus) -> None:
        self._component_statuses[status.component] = status

    def set_system_metric(self, metric: SystemMetric) -> None:
        self._system_metrics[metric.name] = metric

    def set_alerts(self, alerts: Sequence[AlertView]) -> None:
        self._alerts = tuple(alerts)

    def component_statuses(self, components: Optional[Sequence[str]] = None) -> Tuple[ComponentStatus, ...]:
        if components is None:
            return tuple(self._component_statuses.values())
        return tuple(self._component_statuses[c] for c in components if c in self._component_statuses)

    def system_metrics(self) -> Tuple[SystemMetric, ...]:
        return tuple(self._system_metrics.values())

    def alerts(self) -> Tuple[AlertView, ...]:
        return self._alerts
