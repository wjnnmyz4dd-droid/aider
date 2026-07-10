"""Stress tests: a large, varied closed-trade history exercised through
every review/attribution/recommendation path at once (ADR-029 §9)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from phantom.evidence_engine.models import SessionName
from phantom.research_engine.engine import ResearchEngine
from phantom.research_engine.models import ReportPeriod, VolatilityBucket
from phantom.strategy_engine.models import StrategyId
from tests.phantom.research_engine._fixtures import T0, make_config, make_executed_trade, make_rejected_trade, make_trade_history

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
STRATEGIES = [StrategyId.TREND_CONTINUATION, StrategyId.RANGE_REVERSAL, StrategyId.SESSION_BREAKOUT]
SESSIONS = [SessionName.LONDON, SessionName.ASIAN, SessionName.LONDON_NEW_YORK_OVERLAP]
VOLATILITY = [VolatilityBucket.NORMAL, VolatilityBucket.EXPANSION, VolatilityBucket.ABNORMAL]


class TestLargeVariedHistory(unittest.TestCase):
    def test_500_trade_mixed_history_evaluates_without_error(self):
        config = make_config(min_sample_size_for_ranking=10)
        engine = ResearchEngine(config)

        trades = []
        for i in range(480):
            trades.append(make_executed_trade(
                index=i, pair=PAIRS[i % len(PAIRS)], strategy_id=STRATEGIES[i % len(STRATEGIES)],
                session=SESSIONS[i % len(SESSIONS)], won=(i % 3 != 0),
                volatility_bucket=VOLATILITY[i % len(VOLATILITY)],
                liquidity_sweep_occurred=(i % 5 == 0), bos_fvg_occurred=(i % 7 == 0),
                kelly_was_binding=(i % 4 == 0), news_blackout_was_active=(i % 11 == 0),
            ))
        for i in range(480, 500):
            trades.append(make_rejected_trade(index=i, pair=PAIRS[i % len(PAIRS)]))

        history = make_trade_history(trades)
        snapshot = engine.evaluate(
            history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(days=30),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(days=30),
        )

        self.assertEqual(snapshot.sample_size, 480)
        self.assertEqual(len(snapshot.attributions), 13)
        self.assertTrue(snapshot.pair_rankings)
        self.assertTrue(snapshot.strategy_rankings)
        self.assertEqual(snapshot.compliance_effectiveness.rejection_count, 20)


if __name__ == "__main__":
    unittest.main()
