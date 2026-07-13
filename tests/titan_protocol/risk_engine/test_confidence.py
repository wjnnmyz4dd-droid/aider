"""Unit tests: Evidence Score -> confidence tier schedule (ADR-027 Hard
Rule 3), including the task's own verbatim example schedule."""

from __future__ import annotations

import unittest

from titan_protocol.risk_engine.confidence import confidence_tier_for_evidence_score
from tests.titan_protocol.risk_engine._fixtures import make_config


class TestConfidenceSchedule(unittest.TestCase):
    def test_task_example_schedule_bands(self):
        config = make_config()
        cases = [
            (65.0, 0.25), (69.9, 0.25),
            (70.0, 0.50), (74.9, 0.50),
            (75.0, 0.75), (79.9, 0.75),
            (80.0, 1.00), (89.9, 1.00),
            (90.0, 1.25), (100.0, 1.25),
        ]
        for score, expected_r in cases:
            tier = confidence_tier_for_evidence_score(score, config)
            self.assertIsNotNone(tier, f"score {score} produced no tier")
            self.assertAlmostEqual(tier.base_r, expected_r, places=6, msg=f"score={score}")

    def test_below_every_tier_returns_none(self):
        config = make_config()
        self.assertIsNone(confidence_tier_for_evidence_score(10.0, config))

    def test_schedule_is_configurable(self):
        from titan_protocol.risk_engine.models import ConfidenceTier

        custom_schedule = (ConfidenceTier(label="ONLY", min_score=0.0, max_score=100.0, base_r=0.5),)
        config = make_config(confidence_schedule=custom_schedule)
        tier = confidence_tier_for_evidence_score(42.0, config)
        self.assertEqual(tier.label, "ONLY")
        self.assertEqual(tier.base_r, 0.5)


if __name__ == "__main__":
    unittest.main()
