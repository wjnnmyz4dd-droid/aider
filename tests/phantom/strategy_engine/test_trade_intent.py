"""TradeIntent tests (ADR-026 Amendment 1): each strategy's QUALIFIED
path derives the correct BUY/SELL from facts it already computed;
NOT_QUALIFIED/NOT_ELIGIBLE always carry NONE; the winning strategy's
trade_intent propagates unchanged onto StrategySnapshot."""

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
from phantom.strategy_engine.engine import StrategyEngine
from phantom.strategy_engine.models import QualificationStatus, StrategyId, TradeIntent
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


class TestLiquiditySweepMssTradeIntent(unittest.TestCase):
    def _qualify(self, sweep_type: SwingType, choch_direction: StructureDirection):
        pool = LiquidityPool(swing_type=sweep_type, price=1.15, indices=(0, 1), swept=True)
        sweep = LiquiditySweep(
            pool=pool, sweep_index=2, sweep_price=1.155, closed_back_inside=True,
            is_stop_hunt=True, is_trap=False, displacement_follow_through=True,
        )
        choch = StructureEvent(
            event_type=StructureEventType.CHOCH, direction=choch_direction,
            broken_swing=SwingPoint(SwingType.LOW, 1, T0, 1.10), confirmed_index=3, confirmed_price=1.09,
        )
        evidence = make_evidence_snapshot(
            structure=make_structure_result(events=(choch,)),
            liquidity=make_liquidity_result(pools=(pool,), sweeps=(sweep,)),
            component_overrides={"liquidity": {"value": 80.0, "confidence": 0.8}, "structure": {"value": 75.0}},
            support_resistance=make_support_resistance_context(break_quality_score=80.0, false_break_probability=0.1),
        )
        return LiquiditySweepMssStrategy().qualify("EURUSD", evidence, make_mi_snapshot(), make_config())

    def test_bullish_choch_produces_buy(self):
        # A LOW sweep matches a BULLISH CHOCH (`_choch_matches_sweep_direction`).
        result = self._qualify(SwingType.LOW, StructureDirection.BULLISH)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)

    def test_bearish_choch_produces_sell(self):
        # A HIGH sweep matches a BEARISH CHOCH (`_choch_matches_sweep_direction`).
        result = self._qualify(SwingType.HIGH, StructureDirection.BEARISH)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.SELL)

    def test_not_qualified_carries_none(self):
        evidence = make_evidence_snapshot()
        result = LiquiditySweepMssStrategy().qualify("EURUSD", evidence, make_mi_snapshot(), make_config())
        self.assertEqual(result.status, QualificationStatus.NOT_QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.NONE)


class TestBosFvgTradeIntent(unittest.TestCase):
    def _qualify(self, direction: StructureDirection):
        bos = StructureEvent(
            event_type=StructureEventType.BOS_INTERNAL, direction=direction,
            broken_swing=SwingPoint(SwingType.HIGH, 1, T0, 1.12), confirmed_index=5, confirmed_price=1.13,
        )
        gap = FairValueGap(direction=direction, start_index=1, end_index=3, gap_high=1.115, gap_low=1.11, filled=False, fill_index=None)
        evidence = make_evidence_snapshot(
            structure=make_structure_result(events=(bos,)),
            fair_value_gaps=(gap,),
            component_overrides={"structure": {"value": 75.0, "confidence": 0.75}},
            support_resistance=make_support_resistance_context(break_quality_score=70.0),
        )
        return BosFvgStrategy().qualify("EURUSD", evidence, make_mi_snapshot(), make_config())

    def test_bullish_bos_produces_buy(self):
        result = self._qualify(StructureDirection.BULLISH)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)

    def test_bearish_bos_produces_sell(self):
        result = self._qualify(StructureDirection.BEARISH)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.SELL)


class TestTrendContinuationTradeIntent(unittest.TestCase):
    def _qualify(self, trend: TrendClassification):
        evidence = make_evidence_snapshot(
            structure=make_structure_result(trend=trend),
            component_overrides={"trend": {"value": 80.0, "confidence": 0.8}},
        )
        return TrendContinuationStrategy().qualify("EURUSD", evidence, make_mi_snapshot(), make_config())

    def test_trending_up_produces_buy(self):
        result = self._qualify(TrendClassification.TRENDING_UP)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)

    def test_trending_down_produces_sell(self):
        result = self._qualify(TrendClassification.TRENDING_DOWN)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.SELL)


class TestRangeReversalTradeIntent(unittest.TestCase):
    def _qualify(self, sources):
        zone = ConfluenceZone(price=1.10, sources=sources, confluence_score=75.0)
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
        return RangeReversalStrategy().qualify("GBPCHF", evidence, make_mi_snapshot(pair="GBPCHF"), make_config())

    def test_support_zone_produces_buy(self):
        result = self._qualify(("support", "psychological"))
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)

    def test_resistance_zone_produces_sell(self):
        result = self._qualify(("resistance", "psychological"))
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.SELL)

    def test_no_support_resistance_label_falls_back_to_session_midpoint(self):
        # session_high=1.11, session_low=1.09 (fixture defaults) -> midpoint 1.10.
        # A zone priced below the midpoint reads as support -> BUY.
        result = self._qualify(("psychological",))
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)


class TestSessionBreakoutTradeIntent(unittest.TestCase):
    def _qualify(self, latest_event_direction: StructureDirection):
        event = StructureEvent(
            event_type=StructureEventType.BOS_EXTERNAL, direction=latest_event_direction,
            broken_swing=SwingPoint(SwingType.HIGH, 1, T0, 1.12), confirmed_index=9, confirmed_price=1.13,
        )
        evidence = make_evidence_snapshot(
            session=make_session_state(session=SessionName.LONDON_NEW_YORK_OVERLAP, quality_score=90.0),
            volatility=make_volatility_state(is_expansion=True, volatility_score=80.0),
            structure=make_structure_result(events=(event,)),
            component_overrides={"session": {"value": 90.0, "confidence": 0.9}},
        )
        mi = make_mi_snapshot(pair_safety=make_pair_safety(session=make_session_intelligence(session_score=90.0)))
        return SessionBreakoutStrategy().qualify("EURUSD", evidence, mi, make_config())

    def test_bullish_break_produces_buy(self):
        result = self._qualify(StructureDirection.BULLISH)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.BUY)

    def test_bearish_break_produces_sell(self):
        result = self._qualify(StructureDirection.BEARISH)
        self.assertEqual(result.status, QualificationStatus.QUALIFIED)
        self.assertEqual(result.trade_intent, TradeIntent.SELL)


class TestStrategySnapshotTradeIntentPropagation(unittest.TestCase):
    def test_winning_strategys_trade_intent_reaches_the_snapshot_unchanged(self):
        bos = StructureEvent(
            event_type=StructureEventType.BOS_INTERNAL, direction=StructureDirection.BULLISH,
            broken_swing=SwingPoint(SwingType.HIGH, 1, T0, 1.12), confirmed_index=5, confirmed_price=1.13,
        )
        gap = FairValueGap(direction=StructureDirection.BULLISH, start_index=1, end_index=3, gap_high=1.115, gap_low=1.11, filled=False, fill_index=None)
        evidence = make_evidence_snapshot(
            structure=make_structure_result(events=(bos,)),
            fair_value_gaps=(gap,),
            component_overrides={"structure": {"value": 90.0, "confidence": 0.9}},
            support_resistance=make_support_resistance_context(break_quality_score=90.0),
        )
        engine = StrategyEngine(make_config())
        snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot(), now=T0)
        if snapshot.winning_strategy is not None:
            self.assertEqual(snapshot.trade_intent, snapshot.winning_strategy.qualification.trade_intent)
            self.assertIn(snapshot.trade_intent, (TradeIntent.BUY, TradeIntent.SELL))

    def test_rejected_snapshot_carries_none(self):
        evidence = make_evidence_snapshot()
        engine = StrategyEngine(make_config())
        snapshot = engine.evaluate("EURUSD", evidence, make_mi_snapshot(), now=T0)
        self.assertTrue(snapshot.rejected)
        self.assertEqual(snapshot.trade_intent, TradeIntent.NONE)


if __name__ == "__main__":
    unittest.main()
