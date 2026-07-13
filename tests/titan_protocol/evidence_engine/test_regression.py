"""Regression tests: fixed input/output anchors for the exact scenarios
worked through during development, so a future refactor that silently
changes this behavior gets caught."""

from __future__ import annotations

import unittest

from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.liquidity import detect_liquidity_sweeps
from titan_protocol.evidence_engine.models import LiquidityPool, SwingType
from tests.titan_protocol.evidence_engine._fixtures import STRUCTURE_SAMPLE, make_bars, make_config


class TestKnownGoodEvaluation(unittest.TestCase):
    def test_structure_sample_composite_score_is_stable(self):
        # Anchors the exact composite score this fixture series has
        # always produced -- a change here means the scoring pipeline's
        # output changed, which should be a deliberate, reviewed choice.
        engine = EvidenceEngine(make_config())
        bars = make_bars(STRUCTURE_SAMPLE)
        report = engine.evaluate("EURUSD", bars)
        self.assertAlmostEqual(report.score.composite, 41.22756584815049, places=6)

    def test_structure_sample_strongest_candlestick_pattern_is_stable(self):
        engine = EvidenceEngine(make_config())
        bars = make_bars(STRUCTURE_SAMPLE)
        report = engine.evaluate("EURUSD", bars)
        candlestick = next(c for c in report.score.components if c.name == "candlestick")
        self.assertIn("BULLISH_ENGULFING", candlestick.reason)


class TestKnownGoodLiquiditySweep(unittest.TestCase):
    def test_sweep_shape_from_phase2a_manual_verification_is_stable(self):
        # The exact wick-rejection-then-displacement scenario used to
        # verify `detect_liquidity_sweeps` by hand during development.
        bars = make_bars([
            (1.07, 1.08, 1.055, 1.07),
            (1.07, 1.155, 1.065, 1.10),
            (1.10, 1.105, 0.98, 1.00),
        ])
        pool = LiquidityPool(swing_type=SwingType.HIGH, price=1.15, indices=(0,), swept=True)
        sweeps = detect_liquidity_sweeps(bars, (pool,), make_config())
        self.assertEqual(len(sweeps), 1)
        self.assertEqual(sweeps[0].sweep_index, 1)
        self.assertTrue(sweeps[0].is_stop_hunt)
        self.assertTrue(sweeps[0].displacement_follow_through)
        self.assertFalse(sweeps[0].is_trap)


if __name__ == "__main__":
    unittest.main()
