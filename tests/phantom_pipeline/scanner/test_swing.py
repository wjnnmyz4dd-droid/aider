"""Swing-pivot detection and major/minor classification (ADR-002 §5, §13)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import SwingKind, SwingPoint
from phantom_pipeline.scanner.swing import _classify_major_minor, swing_points

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _swing(i: int, price: float, kind: SwingKind) -> SwingPoint:
    return SwingPoint(i, T0 + timedelta(minutes=i), price, kind, is_major=False)


def _bar(i: int, high: float, low: float) -> NormalizedBar:
    close = (high + low) / 2
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=i),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class TestSwingDetection(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig(swing_lookback=2)

    def test_detects_swing_high(self):
        highs = [1.100, 1.101, 1.105, 1.101, 1.100]
        lows = [1.099, 1.0995, 1.100, 1.0995, 1.099]
        bars = [_bar(i, highs[i], lows[i]) for i in range(5)]

        swings = swing_points(bars, self.config, atr_value=None)

        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0].index, 2)
        self.assertEqual(swings[0].kind, SwingKind.HIGH)
        self.assertEqual(swings[0].price, 1.105)

    def test_detects_swing_low(self):
        highs = [1.101, 1.1005, 1.100, 1.1005, 1.101]
        lows = [1.0995, 1.099, 1.095, 1.099, 1.0995]
        bars = [_bar(i, highs[i], lows[i]) for i in range(5)]

        swings = swing_points(bars, self.config, atr_value=None)

        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0].kind, SwingKind.LOW)
        self.assertEqual(swings[0].price, 1.095)

    def test_no_swing_when_no_bar_edges_available(self):
        bars = [_bar(0, 1.100, 1.099), _bar(1, 1.101, 1.0995)]
        self.assertEqual(swing_points(bars, self.config, atr_value=None), ())

    def test_no_swing_in_flat_series(self):
        bars = [_bar(i, 1.100, 1.099) for i in range(6)]
        self.assertEqual(swing_points(bars, self.config, atr_value=None), ())

    def _two_swing_bars(self):
        # A clean swing high at index 2 (1.110), then a clean swing low at
        # index 6 (1.080) — a ~0.030 leg between them.
        highs = [1.100, 1.102, 1.110, 1.102, 1.095, 1.088, 1.083, 1.088, 1.095]
        lows = [1.099, 1.100, 1.105, 1.095, 1.088, 1.083, 1.080, 1.083, 1.088]
        return [_bar(i, highs[i], lows[i]) for i in range(len(highs))]

    def test_major_minor_classification_uses_atr_multiple(self):
        bars = self._two_swing_bars()

        # ~0.030 swing range against a small ATR clears the
        # major_swing_atr_multiple threshold (1.5 * 0.005 = 0.0075).
        swings = swing_points(bars, self.config, atr_value=0.005)
        majors = [s for s in swings if s.is_major]
        self.assertTrue(majors)

    def test_no_atr_reading_yields_no_major_swings(self):
        bars = self._two_swing_bars()

        swings = swing_points(bars, self.config, atr_value=None)
        self.assertFalse(any(s.is_major for s in swings))

    def test_never_mutates_input_bars(self):
        bars = [_bar(i, 1.100 + i * 0.001, 1.099) for i in range(6)]
        before = list(bars)
        swing_points(bars, self.config, atr_value=None)
        self.assertEqual(bars, before)

    def test_two_consecutive_same_kind_swings_from_real_detection_are_never_major(self):
        """End-to-end regression for the audit finding: two consecutive
        SwingKind.HIGH swings with no intervening low (a realistic outcome
        of small fixed-lookback fractal detection in a trending market)
        must not be compared against each other as if their price gap were
        a valid leg — neither has a preceding opposite-kind swing yet."""
        highs = [1.100, 1.102, 1.110, 1.102, 1.100, 1.100, 1.100, 1.160, 1.102, 1.100]
        lows = [1.099, 1.101, 1.109, 1.101, 1.099, 1.099, 1.099, 1.159, 1.101, 1.099]
        bars = [_bar(i, highs[i], lows[i]) for i in range(len(highs))]

        swings = swing_points(bars, self.config, atr_value=0.001)

        self.assertEqual([s.kind for s in swings], [SwingKind.HIGH, SwingKind.HIGH])
        self.assertFalse(any(s.is_major for s in swings))


class TestMajorMinorOppositeKindClassification(unittest.TestCase):
    """Remediation for the audit finding that `_classify_major_minor`
    compared each swing against the immediately preceding swing in list
    order, even when it was the same kind — contradicting the documented
    "immediately preceding opposite-kind swing" rule and letting a
    HIGH-to-HIGH (or LOW-to-LOW) price gap masquerade as a swing leg."""

    ATR = 0.005
    MULTIPLE = 1.5  # ScannerConfig.major_swing_atr_multiple default
    THRESHOLD = ATR * MULTIPLE  # 0.0075

    def test_same_kind_consecutive_swings_are_never_compared_to_each_other(self):
        # Two HIGHs far enough apart to clear the threshold if (incorrectly)
        # compared to each other — but there is no opposite-kind swing
        # before either, so both must be minor.
        points = [
            _swing(0, 1.100, SwingKind.HIGH),
            _swing(1, 1.200, SwingKind.HIGH),  # 0.100 gap vs the first HIGH
        ]
        classified = _classify_major_minor(points, self.ATR, self.MULTIPLE)
        self.assertFalse(any(p.is_major for p in classified))

    def test_classification_uses_the_immediately_preceding_opposite_kind_swing(self):
        # LOW at index 2 is close to the nearer HIGH (index 1) but far from
        # the older HIGH (index 0). Opposite-kind logic must compare it
        # against index 1, classifying it minor; comparing against index 0
        # (the old, incorrect behavior) would have made it major.
        points = [
            _swing(0, 1.000, SwingKind.HIGH),
            _swing(1, 1.100, SwingKind.HIGH),
            _swing(2, 1.099, SwingKind.LOW),  # 0.001 vs index 1, 0.099 vs index 0
        ]
        classified = _classify_major_minor(points, self.ATR, self.MULTIPLE)
        self.assertFalse(classified[2].is_major)  # correct: compares against index 1

    def test_opposite_kind_swing_far_enough_apart_is_classified_major(self):
        points = [
            _swing(0, 1.000, SwingKind.HIGH),
            _swing(1, 1.100, SwingKind.LOW),  # 0.100 gap clears the threshold
        ]
        classified = _classify_major_minor(points, self.ATR, self.MULTIPLE)
        self.assertTrue(classified[1].is_major)

    def test_alternating_swings_unaffected_by_the_fix(self):
        # Strictly alternating swings behave identically to the
        # "previous point in list order" logic this replaces.
        points = [
            _swing(0, 1.000, SwingKind.LOW),
            _swing(1, 1.100, SwingKind.HIGH),
            _swing(2, 1.010, SwingKind.LOW),
            _swing(3, 1.110, SwingKind.HIGH),
        ]
        classified = _classify_major_minor(points, self.ATR, self.MULTIPLE)
        self.assertEqual([p.is_major for p in classified], [False, True, True, True])

    def test_first_swing_of_each_kind_has_no_predecessor_and_is_never_major(self):
        points = [_swing(0, 1.000, SwingKind.HIGH)]
        classified = _classify_major_minor(points, self.ATR, self.MULTIPLE)
        self.assertFalse(classified[0].is_major)


class TestAmendment1ConsistencyAfterSwingFix(unittest.TestCase):
    """Confirms the swing-classification fix keeps Amendment 1's composite
    fields internally consistent — a same-kind-only run of swings must not
    fabricate an external/internal structure reading from a non-leg."""

    def test_only_same_kind_swings_yields_insufficient_external_and_internal_structure(self):
        from phantom_pipeline.scanner import composite

        swings = [
            _swing(0, 1.100, SwingKind.HIGH),
            _swing(1, 1.200, SwingKind.HIGH),
        ]
        # Neither swing is major (no opposite-kind predecessor) per the fix,
        # so both external (major-only) and internal (minor-only) sequence
        # classification see this same single-kind run.
        classified = _classify_major_minor(swings, atr_value=0.005, major_swing_atr_multiple=1.5)
        self.assertFalse(any(s.is_major for s in classified))

        external, internal = composite.external_internal_structure(classified)
        self.assertEqual(external.sequence.name, "INSUFFICIENT_DATA")
        self.assertEqual(internal.sequence.name, "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
