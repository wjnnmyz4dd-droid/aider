"""ComplianceEngineConfig immutability and safe-default tests (ADR-006 §5)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.compliance_engine.config import ComplianceEngineConfig


class TestComplianceEngineConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = ComplianceEngineConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.max_daily_drawdown_percent = 99.0  # type: ignore[misc]

    def test_spread_thresholds_cannot_be_mutated(self):
        config = ComplianceEngineConfig(spread_thresholds={"EURUSD": 0.0005})
        with self.assertRaises(TypeError):
            config.spread_thresholds["GBPUSD"] = 0.0005  # type: ignore[index]

    def test_mutating_caller_supplied_dict_after_construction_does_not_affect_config(self):
        thresholds = {"EURUSD": 0.0005}
        config = ComplianceEngineConfig(spread_thresholds=thresholds)
        thresholds["GBPUSD"] = 0.0007
        self.assertNotIn("GBPUSD", config.spread_thresholds)


class TestSafeDefaults(unittest.TestCase):
    def test_unconfigured_spread_threshold_is_none(self):
        config = ComplianceEngineConfig(spread_thresholds={})
        self.assertIsNone(config.spread_threshold_for("EURUSD"))

    def test_unconfigured_slippage_threshold_is_none(self):
        config = ComplianceEngineConfig(slippage_thresholds={})
        self.assertIsNone(config.slippage_threshold_for("EURUSD"))

    def test_default_session_windows_are_not_empty(self):
        config = ComplianceEngineConfig()
        self.assertGreater(len(config.session_windows), 0)


if __name__ == "__main__":
    unittest.main()
