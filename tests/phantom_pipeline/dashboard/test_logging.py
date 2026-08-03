"""Logging tests — structured only, never `print()`, and a logging
failure never propagates."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from phantom_pipeline.dashboard.logging_sink import log_alert_displayed, log_component_status_displayed, log_view_built
from phantom_pipeline.dashboard.models import AlertView, ComponentStatus, View, ViewName
from tests.phantom_pipeline.dashboard._fixtures import T0


class TestLoggingSink(unittest.TestCase):
    def _view(self) -> View:
        return View(1, ViewName.OVERVIEW, T0, (), (), (), (), None)

    def test_log_view_built_does_not_raise(self):
        log_view_built(self._view())

    def test_log_component_status_displayed_does_not_raise(self):
        log_component_status_displayed("OVERVIEW", ComponentStatus("scanner", "HEALTHY", "ok", "t1", T0))

    def test_log_alert_displayed_does_not_raise(self):
        log_alert_displayed("ALERTS", AlertView("mt5_bridge", "CRITICAL", "CRITICAL", "down", 1, "t2", T0))

    def test_logging_failure_is_swallowed_not_propagated(self):
        with patch("phantom_pipeline.dashboard.logging_sink.logger.log", side_effect=RuntimeError("boom")):
            log_view_built(self._view())  # must not raise


if __name__ == "__main__":
    unittest.main()
