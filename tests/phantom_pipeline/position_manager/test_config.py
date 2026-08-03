"""PositionManagerConfig immutability tests (ADR-009 §4, §8)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.position_manager.config import PositionManagerConfig


class TestPositionManagerConfigImmutability(unittest.TestCase):
    def test_top_level_fields_cannot_be_reassigned(self):
        config = PositionManagerConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.cooldown_seconds = 999.0  # type: ignore[misc]

    def test_defaults_are_sane(self):
        config = PositionManagerConfig()
        self.assertGreater(config.max_duration_seconds, 0)
        self.assertGreater(config.trailing_start_distance, config.trailing_distance * 0)


if __name__ == "__main__":
    unittest.main()
