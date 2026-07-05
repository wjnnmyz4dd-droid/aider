"""Model-level tests (ADR-012 §2, §5, §7) — immutability and the "no new
output objects" guarantee (`INTERFACE_SPECIFICATION.md` §2)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.dashboard.models import ComponentStatus, View, ViewName
from tests.phantom_pipeline.dashboard._fixtures import T0


class TestViewImmutability(unittest.TestCase):
    def _make(self) -> View:
        return View(
            schema_version=1,
            view_name=ViewName.OVERVIEW,
            generated_at=T0,
            component_statuses=[ComponentStatus("scanner", "HEALTHY", "ok", "trace-1", T0)],
            system_metrics=[],
            alerts=[],
            trade_records=[],
            performance=None,
        )

    def test_is_frozen(self):
        view = self._make()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            view.view_name = ViewName.ALERTS

    def test_list_inputs_coerced_to_tuples(self):
        view = self._make()
        self.assertIsInstance(view.component_statuses, tuple)
        self.assertIsInstance(view.system_metrics, tuple)
        self.assertIsInstance(view.alerts, tuple)
        self.assertIsInstance(view.trade_records, tuple)

    def test_all_ten_views_exist(self):
        expected = {
            "OVERVIEW", "TRADING", "RISK", "COMPLIANCE", "EXECUTION",
            "INFRASTRUCTURE", "ANALYTICS", "ALERTS", "RESEARCH", "AUDIT",
        }
        self.assertEqual({v.value for v in ViewName}, expected)


if __name__ == "__main__":
    unittest.main()
