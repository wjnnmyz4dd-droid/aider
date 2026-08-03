"""BOS, CHoCH, liquidity sweep, FVG, order block, support/resistance
(ADR-002 §5, §6, §13). Every case below feeds `compute_structure` a
pre-built swing list directly so each behavior is tested in isolation from
swing detection itself (already covered by `test_swing.py`)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar, SCHEMA_VERSION
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import Direction, StructureKind, SwingKind, SwingPoint
from phantom_pipeline.scanner.structure import compute_structure

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _bar(i: int, o: float, h: float, l: float, c: float) -> NormalizedBar:
    return NormalizedBar(
        schema_version=SCHEMA_VERSION,
        trace_id=f"b{i}",
        symbol="EURUSD",
        timeframe="M1",
        timestamp=T0 + timedelta(minutes=i),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
        quality=DataQuality.NOMINAL,
        is_repaired=False,
        source="test",
    )


class TestBosChoch(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_first_break_is_bos(self):
        swings = [SwingPoint(0, T0, 1.090, SwingKind.LOW, True)]
        bars = [
            _bar(0, 1.090, 1.091, 1.090, 1.0905),
            _bar(1, 1.0905, 1.092, 1.0895, 1.0885),  # break below major low
        ]
        signals, _ = compute_structure(bars, swings, atr_value=None, config=self.config)
        kinds = [s.kind for s in signals]
        self.assertIn(StructureKind.BOS, kinds)
        self.assertNotIn(StructureKind.CHOCH, kinds)

    def test_reversal_break_is_choch(self):
        swings = [
            SwingPoint(0, T0, 1.090, SwingKind.LOW, True),
            SwingPoint(1, T0 + timedelta(minutes=1), 1.100, SwingKind.HIGH, True),
        ]
        bars = [
            _bar(0, 1.090, 1.091, 1.090, 1.0905),
            _bar(1, 1.0905, 1.100, 1.0905, 1.0995),
            _bar(2, 1.0995, 1.102, 1.099, 1.101),  # BOS UP (establishes uptrend)
            _bar(3, 1.101, 1.1015, 1.089, 1.0885),  # break below original major low -> CHoCH
        ]
        signals, _ = compute_structure(bars, swings, atr_value=None, config=self.config)
        choch = [s for s in signals if s.kind == StructureKind.CHOCH]
        self.assertEqual(len(choch), 1)
        self.assertEqual(choch[0].direction, Direction.DOWN)

    def test_no_break_produces_no_bos_or_choch(self):
        swings = [SwingPoint(0, T0, 1.100, SwingKind.HIGH, True)]
        bars = [_bar(i, 1.098, 1.099, 1.097, 1.0985) for i in range(3)]
        signals, _ = compute_structure(bars, swings, atr_value=None, config=self.config)
        kinds = [s.kind for s in signals]
        self.assertNotIn(StructureKind.BOS, kinds)
        self.assertNotIn(StructureKind.CHOCH, kinds)


class TestLiquiditySweep(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_wick_beyond_major_high_with_close_back_inside_is_a_sweep(self):
        swings = [SwingPoint(0, T0, 1.100, SwingKind.HIGH, True)]
        bars = [
            _bar(0, 1.099, 1.100, 1.098, 1.0995),
            _bar(1, 1.0995, 1.103, 1.099, 1.0985),  # wick above, close back below
        ]
        _, events = compute_structure(bars, swings, atr_value=None, config=self.config)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "SWEEP_HIGH")
        self.assertEqual(events[0].direction, Direction.DOWN)
        self.assertEqual(events[0].price, 1.103)

    def test_wick_beyond_major_low_with_close_back_inside_is_a_sweep(self):
        swings = [SwingPoint(0, T0, 1.090, SwingKind.LOW, True)]
        bars = [
            _bar(0, 1.091, 1.092, 1.090, 1.0915),
            _bar(1, 1.0915, 1.092, 1.088, 1.0905),  # wick below, close back above
        ]
        _, events = compute_structure(bars, swings, atr_value=None, config=self.config)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "SWEEP_LOW")
        self.assertEqual(events[0].direction, Direction.UP)
        self.assertEqual(events[0].price, 1.088)


class TestFairValueGap(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_bullish_gap_detected(self):
        bars = [
            _bar(0, 1.100, 1.1010, 1.099, 1.1005),
            _bar(1, 1.1005, 1.1030, 1.1000, 1.1020),
            _bar(2, 1.1020, 1.1050, 1.1025, 1.1040),  # low > bars[0].high -> bullish gap
        ]
        signals, _ = compute_structure(bars, [], atr_value=None, config=self.config)
        fvgs = [s for s in signals if s.kind == StructureKind.FVG]
        self.assertEqual(len(fvgs), 1)
        self.assertEqual(fvgs[0].direction, Direction.UP)

    def test_bearish_gap_detected(self):
        bars = [
            _bar(0, 1.100, 1.1010, 1.0990, 1.0995),
            _bar(1, 1.0980, 1.0990, 1.0960, 1.0970),
            _bar(2, 1.0950, 1.0960, 1.0930, 1.0945),  # high < bars[0].low -> bearish gap
        ]
        signals, _ = compute_structure(bars, [], atr_value=None, config=self.config)
        fvgs = [s for s in signals if s.kind == StructureKind.FVG]
        self.assertEqual(len(fvgs), 1)
        self.assertEqual(fvgs[0].direction, Direction.DOWN)

    def test_no_gap_no_signal(self):
        bars = [_bar(i, 1.100, 1.101, 1.099, 1.1005) for i in range(3)]
        signals, _ = compute_structure(bars, [], atr_value=None, config=self.config)
        self.assertFalse(any(s.kind == StructureKind.FVG for s in signals))


class TestOrderBlock(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_bearish_candle_before_impulsive_bullish_move_is_a_bullish_order_block(self):
        bars = [
            _bar(0, 1.100, 1.1005, 1.0985, 1.099),
            _bar(1, 1.099, 1.110, 1.0985, 1.109),
        ]
        signals, _ = compute_structure(bars, [], atr_value=0.005, config=self.config)
        obs = [s for s in signals if s.kind == StructureKind.ORDER_BLOCK]
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0].direction, Direction.UP)

    def test_no_atr_reading_yields_no_order_blocks(self):
        bars = [
            _bar(0, 1.100, 1.1005, 1.0985, 1.099),
            _bar(1, 1.099, 1.110, 1.0985, 1.109),
        ]
        signals, _ = compute_structure(bars, [], atr_value=None, config=self.config)
        self.assertFalse(any(s.kind == StructureKind.ORDER_BLOCK for s in signals))


class TestSupportResistance(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_major_low_is_support_and_major_high_is_resistance(self):
        swings = [
            SwingPoint(0, T0, 1.090, SwingKind.LOW, True),
            SwingPoint(1, T0 + timedelta(minutes=1), 1.100, SwingKind.HIGH, True),
        ]
        signals, _ = compute_structure([], swings, atr_value=None, config=self.config)
        kinds = {(s.kind, s.detail) for s in signals}
        self.assertIn((StructureKind.SUPPORT, "level 1.09"), kinds)
        self.assertIn((StructureKind.RESISTANCE, "level 1.1"), kinds)

    def test_minor_swings_produce_no_support_resistance(self):
        swings = [SwingPoint(0, T0, 1.090, SwingKind.LOW, False)]
        signals, _ = compute_structure([], swings, atr_value=None, config=self.config)
        self.assertFalse(any(s.kind in (StructureKind.SUPPORT, StructureKind.RESISTANCE) for s in signals))


if __name__ == "__main__":
    unittest.main()
