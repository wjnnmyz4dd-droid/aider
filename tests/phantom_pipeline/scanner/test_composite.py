"""Amendment 1 composite fields (ADR-002 §5, §13, §15)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.scanner import composite
from phantom_pipeline.scanner.config import ScannerConfig
from phantom_pipeline.scanner.models import (
    Direction,
    MarketPhase,
    RangeStructure,
    StructureConfidence,
    StructureTrendState,
    SwingKind,
    SwingPoint,
    SwingSequenceType,
)

T0 = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)


def _swing(i, price, kind, is_major=True):
    return SwingPoint(i, T0 + timedelta(minutes=i), price, kind, is_major)


class TestClassifySequence(unittest.TestCase):
    def test_higher_highs_higher_lows(self):
        swings = [
            _swing(0, 1.090, SwingKind.LOW),
            _swing(1, 1.100, SwingKind.HIGH),
            _swing(2, 1.095, SwingKind.LOW),
            _swing(3, 1.105, SwingKind.HIGH),
        ]
        self.assertEqual(composite.classify_sequence(swings), SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)

    def test_lower_highs_lower_lows(self):
        swings = [
            _swing(0, 1.100, SwingKind.HIGH),
            _swing(1, 1.090, SwingKind.LOW),
            _swing(2, 1.095, SwingKind.HIGH),
            _swing(3, 1.085, SwingKind.LOW),
        ]
        self.assertEqual(composite.classify_sequence(swings), SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)

    def test_mixed_sequence(self):
        swings = [
            _swing(0, 1.090, SwingKind.LOW),
            _swing(1, 1.100, SwingKind.HIGH),
            _swing(2, 1.085, SwingKind.LOW),  # lower low breaks the HH/HL pattern
            _swing(3, 1.105, SwingKind.HIGH),
        ]
        self.assertEqual(composite.classify_sequence(swings), SwingSequenceType.MIXED)

    def test_insufficient_swings(self):
        swings = [_swing(0, 1.090, SwingKind.LOW), _swing(1, 1.100, SwingKind.HIGH)]
        self.assertEqual(composite.classify_sequence(swings), SwingSequenceType.INSUFFICIENT_DATA)


class TestEqualLevels(unittest.TestCase):
    def test_groups_prices_within_tolerance(self):
        swings = [
            _swing(0, 1.1000, SwingKind.HIGH),
            _swing(1, 1.1001, SwingKind.HIGH),  # within tolerance of 1.1000
            _swing(2, 1.2000, SwingKind.HIGH),  # far away, not equal
        ]
        levels = composite.equal_levels(swings, SwingKind.HIGH, tolerance_pct=0.0005)
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0].swing_count, 2)

    def test_no_equal_levels_when_all_unique(self):
        swings = [
            _swing(0, 1.1000, SwingKind.LOW),
            _swing(1, 1.2000, SwingKind.LOW),
        ]
        levels = composite.equal_levels(swings, SwingKind.LOW, tolerance_pct=0.0005)
        self.assertEqual(levels, ())


class TestRangeStructure(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_unknown_ratio_yields_unknown(self):
        self.assertEqual(composite.range_structure(None, self.config), RangeStructure.UNKNOWN)

    def test_high_ratio_yields_expansion(self):
        self.assertEqual(
            composite.range_structure(self.config.volatility_elevated_ratio + 0.1, self.config),
            RangeStructure.EXPANSION,
        )

    def test_low_ratio_yields_compression(self):
        self.assertEqual(
            composite.range_structure(self.config.volatility_compressed_ratio - 0.1, self.config),
            RangeStructure.COMPRESSION,
        )

    def test_mid_ratio_yields_neutral(self):
        self.assertEqual(composite.range_structure(1.0, self.config), RangeStructure.NEUTRAL)


class TestTrendMomentum(unittest.TestCase):
    def test_insufficient_history_yields_unknown(self):
        self.assertEqual(composite.trend_momentum(()), (None, None))
        self.assertEqual(composite.trend_momentum((0.001,)), (None, None))

    def test_increasing_magnitude_is_accelerating(self):
        self.assertEqual(composite.trend_momentum((0.001, 0.002)), (True, False))

    def test_decreasing_magnitude_is_exhausting(self):
        self.assertEqual(composite.trend_momentum((0.002, 0.001)), (False, True))


class TestMarketPhase(unittest.TestCase):
    def test_unknown_when_range_unknown(self):
        external = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        internal = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        self.assertEqual(
            composite.market_phase(external, internal, RangeStructure.UNKNOWN), MarketPhase.UNKNOWN
        )

    def test_expansion_with_uptrend_is_markup(self):
        external = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        internal = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        self.assertEqual(
            composite.market_phase(external, internal, RangeStructure.EXPANSION), MarketPhase.MARKUP
        )

    def test_expansion_with_downtrend_is_markdown(self):
        external = StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)
        internal = StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)
        self.assertEqual(
            composite.market_phase(external, internal, RangeStructure.EXPANSION), MarketPhase.MARKDOWN
        )

    def test_compression_with_internal_uptrend_is_accumulation(self):
        external = StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)
        internal = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        self.assertEqual(
            composite.market_phase(external, internal, RangeStructure.COMPRESSION),
            MarketPhase.ACCUMULATION,
        )

    def test_compression_with_internal_downtrend_is_distribution(self):
        external = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        internal = StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)
        self.assertEqual(
            composite.market_phase(external, internal, RangeStructure.COMPRESSION),
            MarketPhase.DISTRIBUTION,
        )

    def test_never_reports_accumulation_when_internal_swings_show_clear_downtrend(self):
        """Structure-consistency guard (ADR-002 §15): market_phase must
        never contradict the primitive swing facts it was derived from —
        e.g. ACCUMULATION while the (internal) swing hierarchy shows a
        clear LH/LL downtrend would be a contradiction."""
        internal = StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)
        for external_direction in (Direction.UP, Direction.DOWN, Direction.NEUTRAL):
            external = StructureTrendState(external_direction, SwingSequenceType.MIXED)
            for range_state in (RangeStructure.COMPRESSION, RangeStructure.NEUTRAL, RangeStructure.EXPANSION):
                phase = composite.market_phase(external, internal, range_state)
                self.assertNotEqual(phase, MarketPhase.ACCUMULATION)


class TestStructureConfidence(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig(min_swings_for_phase=4)

    def test_insufficient_data_when_too_few_swings(self):
        confidence = composite.structure_confidence(
            [_swing(0, 1.09, SwingKind.LOW)],
            StructureTrendState(Direction.UP, SwingSequenceType.INSUFFICIENT_DATA),
            StructureTrendState(Direction.UP, SwingSequenceType.INSUFFICIENT_DATA),
            self.config,
        )
        self.assertEqual(confidence, StructureConfidence.INSUFFICIENT_DATA)

    def test_clear_when_external_and_internal_agree(self):
        swings = [_swing(i, 1.09 + i * 0.001, SwingKind.LOW) for i in range(5)]
        external = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        internal = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        confidence = composite.structure_confidence(swings, external, internal, self.config)
        self.assertEqual(confidence, StructureConfidence.CLEAR)

    def test_ambiguous_when_sequences_disagree(self):
        swings = [_swing(i, 1.09 + i * 0.001, SwingKind.LOW) for i in range(5)]
        external = StructureTrendState(Direction.UP, SwingSequenceType.HIGHER_HIGHS_HIGHER_LOWS)
        internal = StructureTrendState(Direction.DOWN, SwingSequenceType.LOWER_HIGHS_LOWER_LOWS)
        confidence = composite.structure_confidence(swings, external, internal, self.config)
        self.assertEqual(confidence, StructureConfidence.AMBIGUOUS)


if __name__ == "__main__":
    unittest.main()
