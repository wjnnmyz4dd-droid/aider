"""Unit tests for liquidity analysis: equal levels, pools, sweeps, stop
hunts, the trap filter, and displacement."""

from __future__ import annotations

import unittest

from phantom.evidence_engine.liquidity import (
    build_liquidity_pools,
    detect_displacement,
    detect_liquidity_sweeps,
    find_equal_levels,
)
from phantom.evidence_engine.models import SwingPoint, SwingType
from tests.phantom.evidence_engine._fixtures import make_bars, make_config


class TestEqualLevels(unittest.TestCase):
    def test_clusters_near_equal_highs(self):
        swings = (
            SwingPoint(SwingType.HIGH, 3, None, 1.1500),
            SwingPoint(SwingType.HIGH, 8, None, 1.1503),
        )
        config = make_config()
        levels = find_equal_levels(swings, config.equal_level_tolerance_pct, config.equal_level_min_points)
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0].indices, (3, 8))

    def test_far_apart_highs_are_not_equal(self):
        swings = (
            SwingPoint(SwingType.HIGH, 3, None, 1.10),
            SwingPoint(SwingType.HIGH, 8, None, 1.20),
        )
        config = make_config()
        levels = find_equal_levels(swings, config.equal_level_tolerance_pct, config.equal_level_min_points)
        self.assertEqual(levels, ())

    def test_below_min_points_excluded(self):
        swings = (SwingPoint(SwingType.HIGH, 3, None, 1.15),)
        config = make_config()
        levels = find_equal_levels(swings, config.equal_level_tolerance_pct, config.equal_level_min_points)
        self.assertEqual(levels, ())


class TestLiquidityPools(unittest.TestCase):
    def test_swept_flag_true_once_price_wicks_beyond(self):
        bars = make_bars([
            (1.12, 1.15, 1.115, 1.13), (1.13, 1.135, 1.10, 1.11), (1.11, 1.115, 1.08, 1.09),
            (1.09, 1.10, 1.07, 1.08), (1.08, 1.16, 1.075, 1.10),  # idx4 wicks above 1.15
        ])
        levels = find_equal_levels(
            (SwingPoint(SwingType.HIGH, 0, None, 1.15),), tolerance_pct=0.05, min_points=1
        )
        pools = build_liquidity_pools(levels, bars)
        self.assertTrue(pools[0].swept)

    def test_swept_flag_false_when_never_wicked(self):
        bars = make_bars([(1.12, 1.14, 1.11, 1.13)] * 5)
        levels = find_equal_levels(
            (SwingPoint(SwingType.HIGH, 0, None, 1.15),), tolerance_pct=0.05, min_points=1
        )
        pools = build_liquidity_pools(levels, bars)
        self.assertFalse(pools[0].swept)


class TestLiquiditySweeps(unittest.TestCase):
    def test_stop_hunt_with_displacement_is_not_a_trap(self):
        bars = make_bars([
            (1.07, 1.08, 1.055, 1.07),
            (1.07, 1.155, 1.065, 1.10),   # idx1: wicks above 1.15, closes back below -> stop hunt
            (1.10, 1.105, 0.98, 1.00),    # idx2: large-range reversal bar -> displacement follow-through
        ])
        levels = find_equal_levels(
            (SwingPoint(SwingType.HIGH, 0, None, 1.15),), tolerance_pct=0.05, min_points=1
        )
        pools = build_liquidity_pools(levels, bars)
        config = make_config()
        sweeps = detect_liquidity_sweeps(bars, pools, config)
        self.assertEqual(len(sweeps), 1)
        self.assertTrue(sweeps[0].is_stop_hunt)
        self.assertTrue(sweeps[0].displacement_follow_through)
        self.assertFalse(sweeps[0].is_trap)

    def test_stop_hunt_without_displacement_is_a_trap(self):
        bars = make_bars([
            (1.07, 1.08, 1.055, 1.07),
            (1.07, 1.155, 1.065, 1.10),   # wicks above 1.15, closes back below -> stop hunt shape
            (1.10, 1.105, 1.098, 1.102),  # idx2: weak, tiny-range bar -> no displacement
        ])
        levels = find_equal_levels(
            (SwingPoint(SwingType.HIGH, 0, None, 1.15),), tolerance_pct=0.05, min_points=1
        )
        pools = build_liquidity_pools(levels, bars)
        config = make_config()
        sweeps = detect_liquidity_sweeps(bars, pools, config)
        self.assertEqual(len(sweeps), 1)
        self.assertTrue(sweeps[0].is_stop_hunt)
        self.assertFalse(sweeps[0].displacement_follow_through)
        self.assertTrue(sweeps[0].is_trap)

    def test_genuine_breakout_is_not_a_stop_hunt(self):
        # Wicks above the pool AND closes above it too -- a real
        # breakout continuation, not a wick-rejection shape.
        bars = make_bars([
            (1.07, 1.08, 1.055, 1.07),
            (1.07, 1.17, 1.065, 1.165),  # closes above 1.15, not back below -> no rejection
        ])
        levels = find_equal_levels(
            (SwingPoint(SwingType.HIGH, 0, None, 1.15),), tolerance_pct=0.05, min_points=1
        )
        pools = build_liquidity_pools(levels, bars)
        config = make_config()
        sweeps = detect_liquidity_sweeps(bars, pools, config)
        self.assertEqual(len(sweeps), 1)
        self.assertFalse(sweeps[0].is_stop_hunt)
        self.assertFalse(sweeps[0].is_trap)

    def test_unswept_pool_produces_no_sweep(self):
        bars = make_bars([(1.12, 1.14, 1.11, 1.13)] * 5)
        levels = find_equal_levels(
            (SwingPoint(SwingType.HIGH, 0, None, 1.15),), tolerance_pct=0.05, min_points=1
        )
        pools = build_liquidity_pools(levels, bars)
        config = make_config()
        sweeps = detect_liquidity_sweeps(bars, pools, config)
        self.assertEqual(sweeps, ())


class TestDisplacementDetection(unittest.TestCase):
    def test_flags_large_range_bar(self):
        bars = make_bars([(1.10, 1.105, 1.095, 1.10)] * 10 + [(1.10, 1.30, 1.05, 1.28)])
        config = make_config()
        indices = detect_displacement(bars, config)
        self.assertIn(10, indices)

    def test_empty_series_returns_empty(self):
        self.assertEqual(detect_displacement((), make_config()), ())


if __name__ == "__main__":
    unittest.main()
