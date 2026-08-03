"""Dashboard-only metrics tests — export-only, additive, zero effect on
returned outputs (same discipline as every prior stage's metrics)."""

from __future__ import annotations

import unittest

from phantom_pipeline.dashboard.metrics import DashboardMetrics
from phantom_pipeline.dashboard.models import ViewName


class TestDashboardMetrics(unittest.TestCase):
    def test_view_built_counts_increment(self):
        metrics = DashboardMetrics()
        metrics.record_view_built(ViewName.OVERVIEW)
        metrics.record_view_built(ViewName.OVERVIEW)
        metrics.record_view_built(ViewName.ALERTS)
        self.assertEqual(metrics.views_built.get("OVERVIEW"), 2)
        self.assertEqual(metrics.views_built.get("ALERTS"), 1)

    def test_snapshots_are_copies_not_live_views(self):
        metrics = DashboardMetrics()
        metrics.record_view_built(ViewName.OVERVIEW)
        snapshot = metrics.views_built
        snapshot["INJECTED"] = 999
        self.assertNotIn("INJECTED", metrics.views_built)


if __name__ == "__main__":
    unittest.main()
