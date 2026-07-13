"""Performance category: a moderately large historical run and closed-
trade history must evaluate within a bounded time budget (ADR-030 §9)."""

from __future__ import annotations

import time
import unittest

from titan_protocol.strategy_engine.models import StrategyId
from titan_protocol.validation_engine.config import ValidationEngineConfig
from titan_protocol.validation_engine.engine import ValidationEngine
from tests.titan_protocol.validation_engine._fixtures import (
    T0,
    make_execution_record,
    make_repeating_executed_trades,
    make_run,
    make_scenario,
    make_trade_history,
)

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURJPY"]
STRATEGIES = [StrategyId.TREND_CONTINUATION, StrategyId.RANGE_REVERSAL, StrategyId.SESSION_BREAKOUT]


class TestPerformance(unittest.TestCase):
    def test_moderately_large_run_evaluates_within_budget(self):
        config = ValidationEngineConfig()
        engine = ValidationEngine(config)

        scenarios = [
            make_scenario(scenario_id=f"SCN-{i}", pair=PAIRS[i % len(PAIRS)], execution=make_execution_record())
            for i in range(50)
        ]
        run = make_run(scenarios)

        trades = []
        for i, pair in enumerate(PAIRS):
            trades.extend(make_repeating_executed_trades(
                count=30, win_r=2.0, loss_r=-1.0, win_rate=0.5, pair=pair, strategy_id=STRATEGIES[i % len(STRATEGIES)],
            ))
        history = make_trade_history(trades)

        start = time.monotonic()
        snapshot = engine.evaluate(run, history, now=T0)
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 10.0, f"evaluate() took {elapsed:.2f}s, expected under 10s")
        self.assertEqual(len(snapshot.replay_verifications), 50)
        self.assertTrue(snapshot.strategy_tournament)


if __name__ == "__main__":
    unittest.main()
