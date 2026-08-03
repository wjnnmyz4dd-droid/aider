"""A real `PrometheusReadPort` backed by Prometheus's HTTP query API
(ADR-012 §4, §9; ADR-015's Adapter Forbidden Responsibilities).

**Read-only, translation only.** Every method here issues exactly one
`GET /api/v1/query` against a running Prometheus server and maps the
response into this package's existing `ComponentStatus`/`SystemMetric`/
`AlertView` dataclasses — the same three shapes `FakePrometheusReadPort`
already returns, so `DashboardEngine` (which only ever calls
`PrometheusReadPort`'s three abstract methods) needs no change to consume
real data instead of a test double. There is no `set_*`/`write_*` method
here, mirroring the ABC's own structural read-only guarantee (§4, §9).

**The metric-naming convention this adapter expects.** Prometheus values
are always numeric; `ComponentStatus.health_state`/`reason`/`trace_id` and
`AlertView`'s string fields cannot be carried as a Prometheus *value* — so,
following Prometheus's own established "info metric" idiom (fixed value of
`1`, the actual data carried entirely in labels — the same pattern
`kube_pod_info`-style exporters use), this adapter expects:
  - `phantom_component_health_state{component, state, reason, trace_id}`
  - `phantom_alert{component, alert_class, severity, detail, repeat_count,
    trace_id}`
  - `phantom_system_metric{name, unit}` — value is the metric's own float
    reading directly (this one needs no info-metric trick; a numeric
    metric is Prometheus's native case).
No exporter emitting these series in this exact shape exists yet anywhere
in this repository (each stage's own `metrics.py` is still an in-memory
counter object, not a `/metrics` HTTP endpoint) — this is a real,
documented Phase 3 gap, not something this adapter's read side can close
on its own (see `docs/plans/phase3-real-adapters.md`).

**Failure behavior.** Any query failure (timeout, connection error,
non-2xx, malformed body) is caught and logged; the method returns an empty
tuple rather than raising or crashing the Dashboard — consistent with
"Dashboard remains read-only" and never blocking a human viewer's render
because one Prometheus query hiccuped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import AlertView, ComponentStatus, SystemMetric
from .prometheus_port import PrometheusReadPort

logger = logging.getLogger(__name__)


class PrometheusAdapter(PrometheusReadPort):
    def __init__(self, base_url: str, session: Optional[Any] = None, timeout_seconds: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        if session is not None:
            self._session = session
        else:
            import requests  # local import: keep this module importable without requests installed

            self._session = requests.Session()

    def _query(self, promql: str) -> List[Dict[str, Any]]:
        try:
            response = self._session.get(
                f"{self._base_url}/api/v1/query",
                params={"query": promql},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logger.warning("PrometheusAdapter query failed: %s", promql, exc_info=True)
            return []
        if payload.get("status") != "success":
            logger.warning("PrometheusAdapter query returned non-success status: %s", promql)
            return []
        return payload.get("data", {}).get("result", [])

    def component_statuses(self, components: Optional[Sequence[str]] = None) -> Tuple[ComponentStatus, ...]:
        promql = "phantom_component_health_state"
        if components:
            pattern = "|".join(components)
            promql = f'phantom_component_health_state{{component=~"{pattern}"}}'
        statuses = []
        for series in self._query(promql):
            labels = series.get("metric", {})
            timestamp = _series_timestamp(series)
            statuses.append(
                ComponentStatus(
                    component=labels.get("component", ""),
                    health_state=labels.get("state", ""),
                    reason=labels.get("reason", ""),
                    trace_id=labels.get("trace_id", ""),
                    timestamp=timestamp,
                )
            )
        return tuple(statuses)

    def system_metrics(self) -> Tuple[SystemMetric, ...]:
        metrics = []
        for series in self._query("phantom_system_metric"):
            labels = series.get("metric", {})
            timestamp = _series_timestamp(series)
            metrics.append(
                SystemMetric(
                    name=labels.get("name", ""),
                    value=_series_value(series),
                    unit=labels.get("unit", ""),
                    timestamp=timestamp,
                )
            )
        return tuple(metrics)

    def alerts(self) -> Tuple[AlertView, ...]:
        alerts = []
        for series in self._query("phantom_alert"):
            labels = series.get("metric", {})
            timestamp = _series_timestamp(series)
            alerts.append(
                AlertView(
                    component=labels.get("component", ""),
                    alert_class=labels.get("alert_class", ""),
                    severity=labels.get("severity", ""),
                    detail=labels.get("detail", ""),
                    repeat_count=int(labels.get("repeat_count", "0")),
                    trace_id=labels.get("trace_id", ""),
                    timestamp=timestamp,
                )
            )
        return tuple(alerts)


def _series_value(series: Dict[str, Any]) -> float:
    _, value = series.get("value", (0, "0"))
    return float(value)


def _series_timestamp(series: Dict[str, Any]) -> datetime:
    ts, _ = series.get("value", (0, "0"))
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


__all__ = ["PrometheusAdapter"]
