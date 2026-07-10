"""Qualification tests: each strategy's regime self-check, pair
eligibility gate, and a genuine QUALIFIED path constructed by hand."""

from __future__ import annotations

import unittest

from phantom.evidence_engine.models import (
    CandlestickMatch,
    CandlestickPattern,
    ConfluenceZone,
    FairValueGap,
    LiquidityPool,
    LiquiditySweep,
    PatternContext,
    SessionName,
    StructureDirection,
    StructureEvent,
    StructureEventType,
    SwingPoint,
    SwingType,
    TrendClassification,
)
from phantom.strategy_engine.models import QualificationStatus, StrategyId
from phantom.strategy_engine.strategies import (
    BosFvgStrategy,
    LiquiditySweepMssStrategy,
    RangeReversalStrategy,
    SessionBreakoutStrategy,
    TrendContinuationStrategy,
)
from tests.phantom.strategy_engine._fixtures import (
    T0,
    make_config,
    make_evidence_snapshot,
    make_liquidity_result,
    make_mi_snapshot,
    make_pair_safety,
    make_session_intelligence,
    make_session_state,
    make_structure_result,
    make_support_resistance_context,
    make_volatility_state,
)


class TestPairEligibilityGate(unittest.TestCase):
    def test_ineligible_pair_returns_not_eligible_with_zero_score(self):
        strategy = LiquiditySweepMssStrategy()
        evidence = make_evidence_snapshot(symbol="XAUUSD")
        mi = make_mi_snapshot(pair="XAUUSD")
        result = strategy.qualify("XAUUSD", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_ELIGIBLE)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.reason, "Pair not supported by strategy")

    def test_never_partially_eligible(self):
        # Confirms NOT_ELIGIBLE short-circuits before any other logic --
        # even with evidence that would otherwise strongly qualify.
        strategy = TrendContinuationStrategy()
        evidence = make_evidence_snapshot(
            symbol="EURSEK",
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": 95.0, "confidence": 0.95}},
        )
        mi = make_mi_snapshot(pair="EURSEK")
        result = strategy.qualify("EURSEK", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_ELIGIBLE)


class TestLiquiditySweepMss(unittest.TestCase):
    def test_no_qualifying_sweep_choch_combination_disqualifies(self):
        strategy = LiquiditySweepMssStrategy()
        evidence = make_evidence_snapshot()
        mi = make_mi_snapshot()
        result = strategy.qualify("EURUSD", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_genuine_sweep_plus_confirming_choch_qualifies(self):
        pool = LiquidityPool(swing_type=SwingType.HIGH, price=1.15, indices=(0, 1), swept=True)
        sweep = LiquiditySweep(
            pool=pool, sweep_index=2, sweep_price=1.155, closed_back_inside=True,
            is_stop_hunt=True, is_trap=False, displacement_follow_through=True,
        )
        choch = StructureEvent(
            event_type=StructureEventType.CHOCH, direction=StructureDirection.BEARISH,
            broken_swing=SwingPoint(SwingType.LOW, 1, T0, 1.10), confirmed_index=3, confirmed_price=1.09,
        )
        evidence = make_evidence_snapshot(
            structure=make_structure_result(events=(choch,)),
            liquidity=make_liquidity_result(pools=(pool,), sweeps=(sweep,)),
            component_overrides={"liquidity": {"value": 80.0, "confidence": 0.8}, "structure": {"value": 75.0}},
            support_resistance=make_support_resistance_context(break_quality_score=80.0, false_break_probability=0.1),
        )
        mi = make_mi_snapshot()
        result = strategy_qualify_liquidity_sweep(evidence, mi)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertGreater(result.score, 0.0)
        self.assertTrue(result.strengths)

    def test_trap_sweep_with_no_choch_disqualifies(self):
        pool = LiquidityPool(swing_type=SwingType.HIGH, price=1.15, indices=(0, 1), swept=True)
        sweep = LiquiditySweep(
            pool=pool, sweep_index=2, sweep_price=1.155, closed_back_inside=True,
            is_stop_hunt=True, is_trap=True, displacement_follow_through=False,
        )
        evidence = make_evidence_snapshot(liquidity=make_liquidity_result(pools=(pool,), sweeps=(sweep,)))
        mi = make_mi_snapshot()
        result = strategy_qualify_liquidity_sweep(evidence, mi)
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)


def strategy_qualify_liquidity_sweep(evidence, mi):
    return LiquiditySweepMssStrategy().qualify("EURUSD", evidence, mi, make_config())


class TestBosFvg(unittest.TestCase):
    def test_no_matching_bos_and_gap_disqualifies(self):
        strategy = BosFvgStrategy()
        evidence = make_evidence_snapshot()
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_bos_with_matching_unfilled_gap_qualifies(self):
        bos = StructureEvent(
            event_type=StructureEventType.BOS_INTERNAL, direction=StructureDirection.BULLISH,
            broken_swing=SwingPoint(SwingType.HIGH, 1, T0, 1.12), confirmed_index=5, confirmed_price=1.13,
        )
        gap = FairValueGap(
            direction=StructureDirection.BULLISH, start_index=1, end_index=3,
            gap_high=1.115, gap_low=1.11, filled=False, fill_index=None,
        )
        evidence = make_evidence_snapshot(
            structure=make_structure_result(events=(bos,)),
            fair_value_gaps=(gap,),
            component_overrides={"structure": {"value": 75.0, "confidence": 0.75}},
            support_resistance=make_support_resistance_context(break_quality_score=70.0),
        )
        strategy = BosFvgStrategy()
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertGreater(result.score, 0.0)

    def test_filled_gap_does_not_qualify(self):
        bos = StructureEvent(
            event_type=StructureEventType.BOS_INTERNAL, direction=StructureDirection.BULLISH,
            broken_swing=SwingPoint(SwingType.HIGH, 1, T0, 1.12), confirmed_index=5, confirmed_price=1.13,
        )
        gap = FairValueGap(
            direction=StructureDirection.BULLISH, start_index=1, end_index=3,
            gap_high=1.115, gap_low=1.11, filled=True, fill_index=4,
        )
        evidence = make_evidence_snapshot(structure=make_structure_result(events=(bos,)), fair_value_gaps=(gap,))
        strategy = BosFvgStrategy()
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)


class TestTrendContinuation(unittest.TestCase):
    def test_ranging_market_disqualifies(self):
        strategy = TrendContinuationStrategy()
        evidence = make_evidence_snapshot(structure=make_structure_result(trend=TrendClassification.RANGE))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_directional_trend_with_strong_score_qualifies(self):
        strategy = TrendContinuationStrategy()
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"trend": {"value": 80.0, "confidence": 0.8}},
            volatility=make_volatility_state(is_expansion=True, volatility_score=70.0),
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertIn("volatility expanding", " ".join(result.strengths))

    def test_weak_trend_score_disqualifies_even_if_directional(self):
        strategy = TrendContinuationStrategy()
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=TrendClassification.TRENDING_DOWN),
            component_overrides={"trend": {"value": 20.0}},
        )
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)


class TestSessionBreakout(unittest.TestCase):
    def test_off_session_disqualifies(self):
        strategy = SessionBreakoutStrategy()
        evidence = make_evidence_snapshot(session=make_session_state(session=SessionName.ASIAN))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_no_volatility_expansion_disqualifies(self):
        strategy = SessionBreakoutStrategy()
        evidence = make_evidence_snapshot(volatility=make_volatility_state(is_expansion=False))
        result = strategy.qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_news_blackout_disqualifies(self):
        from tests.phantom.strategy_engine._fixtures import make_pair_news_intelligence

        strategy = SessionBreakoutStrategy()
        evidence = make_evidence_snapshot(volatility=make_volatility_state(is_expansion=True, volatility_score=80.0))
        mi = make_mi_snapshot(pair_safety=make_pair_safety(news=make_pair_news_intelligence(blackout_active=True, blackout_reason="NFP")))
        result = strategy.qualify("EURUSD", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertIn("blackout", result.reason.lower())

    def test_preferred_session_with_expansion_qualifies(self):
        strategy = SessionBreakoutStrategy()
        evidence = make_evidence_snapshot(
            session=make_session_state(session=SessionName.LONDON_NEW_YORK_OVERLAP, quality_score=90.0),
            volatility=make_volatility_state(is_expansion=True, volatility_score=80.0),
            structure=make_structure_result(trend=TrendClassification.TRENDING_UP),
            component_overrides={"session": {"value": 90.0, "confidence": 0.9}},
        )
        mi = make_mi_snapshot(pair_safety=make_pair_safety(session=make_session_intelligence(session_score=90.0)))
        result = strategy.qualify("EURUSD", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)

    def test_no_directional_fact_disqualifies_fail_closed(self):
        strategy = SessionBreakoutStrategy()
        evidence = make_evidence_snapshot(
            session=make_session_state(session=SessionName.LONDON_NEW_YORK_OVERLAP, quality_score=90.0),
            volatility=make_volatility_state(is_expansion=True, volatility_score=80.0),
            structure=make_structure_result(trend=TrendClassification.RANGE),
            component_overrides={"session": {"value": 90.0, "confidence": 0.9}},
        )
        mi = make_mi_snapshot(pair_safety=make_pair_safety(session=make_session_intelligence(session_score=90.0)))
        result = strategy.qualify("EURUSD", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertIn("no directional fact", result.reason.lower())


class TestRangeReversal(unittest.TestCase):
    def test_directional_trend_disqualifies(self):
        strategy = RangeReversalStrategy()
        evidence = make_evidence_snapshot(symbol="GBPCHF", structure=make_structure_result(trend=TrendClassification.TRENDING_UP))
        mi = make_mi_snapshot(pair="GBPCHF")
        result = strategy.qualify("GBPCHF", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_no_confluence_zone_disqualifies(self):
        strategy = RangeReversalStrategy()
        evidence = make_evidence_snapshot(symbol="GBPCHF", structure=make_structure_result(trend=TrendClassification.RANGE))
        mi = make_mi_snapshot(pair="GBPCHF")
        result = strategy.qualify("GBPCHF", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)

    def test_confluence_plus_candlestick_qualifies(self):
        zone = ConfluenceZone(price=1.10, sources=("support", "psychological", "session_low"), confluence_score=75.0)
        candle = CandlestickMatch(
            pattern=CandlestickPattern.BULLISH_ENGULFING, index=10, quality=0.9,
            context=PatternContext.AT_DOWNTREND_EXTREME, confidence=0.85,
        )
        evidence = make_evidence_snapshot(
            symbol="GBPCHF",
            structure=make_structure_result(trend=TrendClassification.RANGE),
            support_resistance=make_support_resistance_context(confluence_zones=(zone,), false_break_probability=0.2),
            candlesticks=(candle,),
            component_overrides={"trend": {"value": 20.0}},
        )
        mi = make_mi_snapshot(pair="GBPCHF")
        strategy = RangeReversalStrategy()
        result = strategy.qualify("GBPCHF", evidence, mi, make_config())
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertGreater(result.score, 0.0)


if __name__ == "__main__":
    unittest.main()
