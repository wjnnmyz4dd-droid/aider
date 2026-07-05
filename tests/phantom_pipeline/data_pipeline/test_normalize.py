"""Normalization correctness, timestamp correctness, timezone correctness
(VALIDATION_MATRIX.md §1 / ADR-013 §16)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from phantom_pipeline.data_pipeline.config import PipelineConfig
from phantom_pipeline.data_pipeline.normalize import (
    normalize_price,
    normalize_symbol,
    normalize_timestamp,
    normalize_volume,
)


class TestSymbolNormalization(unittest.TestCase):
    def test_maps_alias_to_canonical(self):
        config = PipelineConfig(symbol_aliases={"EURUSD.a": "EURUSD"})
        self.assertEqual(normalize_symbol("EURUSD.a", config), "EURUSD")

    def test_unaliased_symbol_passes_through(self):
        config = PipelineConfig()
        self.assertEqual(normalize_symbol("EURUSD", config), "EURUSD")


class TestTimestampNormalization(unittest.TestCase):
    def test_converts_to_utc(self):
        ny = datetime(2026, 7, 4, 9, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        normalized = normalize_timestamp(ny)
        self.assertEqual(normalized.tzinfo, timezone.utc)
        self.assertEqual(normalized.hour, 13)  # EDT is UTC-4 in July

    def test_utc_input_is_idempotent(self):
        ts = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(normalize_timestamp(ts), ts)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            normalize_timestamp(datetime(2026, 7, 4, 12, 0, 0))


class TestPricePrecision(unittest.TestCase):
    def test_default_precision(self):
        config = PipelineConfig()
        self.assertEqual(normalize_price(1.234567, "EURUSD", config), 1.23457)

    def test_per_symbol_precision_override(self):
        config = PipelineConfig(price_precision_digits={"USDJPY": 3})
        self.assertEqual(normalize_price(150.12345, "USDJPY", config), 150.123)

    def test_non_positive_price_rejected(self):
        config = PipelineConfig()
        with self.assertRaises(ValueError):
            normalize_price(0.0, "EURUSD", config)
        with self.assertRaises(ValueError):
            normalize_price(-1.0, "EURUSD", config)


class TestVolumeNormalization(unittest.TestCase):
    def test_rounds_to_configured_precision(self):
        config = PipelineConfig(volume_precision_digits=1)
        self.assertEqual(normalize_volume(1.26, config), 1.3)

    def test_negative_volume_rejected(self):
        config = PipelineConfig()
        with self.assertRaises(ValueError):
            normalize_volume(-1.0, config)


if __name__ == "__main__":
    unittest.main()
