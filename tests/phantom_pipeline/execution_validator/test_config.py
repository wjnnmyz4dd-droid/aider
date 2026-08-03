"""ExecutionValidatorConfig immutability and safe-default tests (ADR-007 §6, §9)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.execution_validator.config import ExecutionValidatorConfig


class TestExecutionValidatorConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = ExecutionValidatorConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.max_order_age_seconds = 999.0  # type: ignore[misc]

    def test_max_spread_cannot_be_mutated(self):
        config = ExecutionValidatorConfig(max_spread={"EURUSD": 0.0005})
        with self.assertRaises(TypeError):
            config.max_spread["GBPUSD"] = 0.0005  # type: ignore[index]

    def test_mutating_caller_supplied_dict_after_construction_does_not_affect_config(self):
        thresholds = {"EURUSD": 0.0005}
        config = ExecutionValidatorConfig(max_spread=thresholds)
        thresholds["GBPUSD"] = 0.0007
        self.assertNotIn("GBPUSD", config.max_spread)


class TestSafeDefaults(unittest.TestCase):
    def test_unconfigured_spread_threshold_is_none(self):
        config = ExecutionValidatorConfig(max_spread={})
        self.assertIsNone(config.max_spread_for("EURUSD"))


if __name__ == "__main__":
    unittest.main()
