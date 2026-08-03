"""ScannerConfig immutability and symbol-registry semantics (ADR-002 §9)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.scanner.config import ScannerConfig


class TestScannerConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = ScannerConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.swing_lookback = 5  # type: ignore[misc]

    def test_recognized_symbols_mapping_cannot_be_mutated(self):
        config = ScannerConfig(recognized_symbols={"EURUSD": True})
        with self.assertRaises(TypeError):
            config.recognized_symbols["GBPUSD"] = True  # type: ignore[index]

    def test_mutating_caller_supplied_dict_after_construction_does_not_affect_config(self):
        registry = {"EURUSD": True}
        config = ScannerConfig(recognized_symbols=registry)
        registry["GBPUSD"] = True
        self.assertNotIn("GBPUSD", config.recognized_symbols)


class TestSymbolRecognition(unittest.TestCase):
    def test_empty_registry_means_no_restriction(self):
        config = ScannerConfig()
        self.assertTrue(config.is_symbol_recognized("ANYTHING"))

    def test_nonempty_registry_is_an_allow_list(self):
        config = ScannerConfig(recognized_symbols={"EURUSD": True})
        self.assertTrue(config.is_symbol_recognized("EURUSD"))
        self.assertFalse(config.is_symbol_recognized("GBPUSD"))


if __name__ == "__main__":
    unittest.main()
