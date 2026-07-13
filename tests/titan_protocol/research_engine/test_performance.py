"""Performance tests: a realistic multi-pair, multi-hundred-trade
history evaluated well within budget (ADR-029 §9)."""

from __future__ import annotations

import time
import unittest
from datetime import timedelta

from titan_protocol.research_engine.engine import ResearchEngine
from titan_protocol.research_engine.models import ReportPeriod
from tests.titan_protocol.research_engine._fixtures import T0, make_config, make_repeating_executed_trades, make_trade_history

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF",
    "CHFJPY",
]


class TestMultiPairPerformance(unittest.TestCase):
    def test_28_plus_pairs_worth_of_history_within_budget(self):
        self.assertGreaterEqual(len(PAIRS), 28)
        config = make_config(min_sample_size_for_ranking=10)
        engine = ResearchEngine(config)

        trades = []
        for pair in PAIRS:
            trades += make_repeating_executed_trades(count=20, pair=pair, start=T0)

        history = make_trade_history(trades)
        start = time.perf_counter()
        snapshot = engine.evaluate(
            history, period=ReportPeriod.CUSTOM, now=T0 + timedelta(days=10),
            custom_start=T0 - timedelta(hours=1), custom_end=T0 + timedelta(days=10),
        )
        elapsed = time.perf_counter() - start

        self.assertEqual(snapshot.sample_size, len(trades))
        self.assertLess(elapsed, 10.0, f"28-pair evaluation took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
