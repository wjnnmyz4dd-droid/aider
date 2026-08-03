"""PipelineConfig immutability — remediation for the audit finding that
frozen=True did not extend to the dict-typed fields."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.data_pipeline.config import PipelineConfig


class TestPipelineConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = PipelineConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.default_price_precision_digits = 10  # type: ignore[misc]

    def test_symbol_aliases_mapping_cannot_be_mutated(self):
        config = PipelineConfig(symbol_aliases={"EURUSD.a": "EURUSD"})
        with self.assertRaises(TypeError):
            config.symbol_aliases["GBPUSD.a"] = "GBPUSD"  # type: ignore[index]

    def test_price_precision_digits_mapping_cannot_be_mutated(self):
        config = PipelineConfig()
        with self.assertRaises(TypeError):
            config.price_precision_digits["EURUSD"] = 3  # type: ignore[index]

    def test_timeframe_seconds_mapping_cannot_be_mutated(self):
        config = PipelineConfig()
        with self.assertRaises(TypeError):
            config.timeframe_seconds["M1"] = 30  # type: ignore[index]

    def test_mutating_the_caller_supplied_dict_after_construction_does_not_affect_config(self):
        aliases = {"EURUSD.a": "EURUSD"}
        config = PipelineConfig(symbol_aliases=aliases)
        aliases["GBPUSD.a"] = "GBPUSD"  # mutate the original dict
        self.assertNotIn("GBPUSD.a", config.symbol_aliases)  # config took its own copy

    def test_values_still_readable_normally(self):
        config = PipelineConfig(symbol_aliases={"EURUSD.a": "EURUSD"})
        self.assertEqual(config.symbol_aliases["EURUSD.a"], "EURUSD")
        self.assertEqual(config.interval_seconds_for("M1"), 60)


if __name__ == "__main__":
    unittest.main()
