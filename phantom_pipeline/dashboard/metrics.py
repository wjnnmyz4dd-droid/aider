"""Dashboard-only metrics surface (ADR-012 — same discipline every prior
stage's metrics module already established).

Export-only, additive — recording a metric has zero effect on any
returned output. This is the Dashboard's own operational metric surface
(how many times each view was rendered) — not to be confused with the
metrics the Dashboard *displays*, which come from Prometheus/Analytics
and are never recomputed here (§8).
"""

from __future__ import annotations

from typing import Dict

from .models import ViewName


class DashboardMetrics:
    def __init__(self) -> None:
        self._views_built: Dict[str, int] = {}

    def record_view_built(self, view_name: ViewName) -> None:
        self._views_built[view_name.value] = self._views_built.get(view_name.value, 0) + 1

    @property
    def views_built(self) -> Dict[str, int]:
        return dict(self._views_built)
