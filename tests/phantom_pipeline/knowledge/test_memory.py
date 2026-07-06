"""TradeMemoryStore tests — dedup by trace_id, find_by filtering, thread
safety (ADR-020 §3)."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge.memory import TradeMemoryStore
from phantom_pipeline.knowledge.models import TradeMemoryRecord
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _record(trace_id, symbol="EURUSD", sessions=("LONDON",), market_regime="MARKUP", strategy_id="ORB") -> TradeMemoryRecord:
    return TradeMemoryRecord(
        schema_version=1, trace_id=trace_id, symbol=symbol, direction=Direction.UP,
        entry_price=1.1, exit_price=1.2, sessions=sessions, market_regime=market_regime,
        strategy_id=strategy_id, score_total=75.0, risk_tier="NORMAL", compliance_verdict="APPROVE",
        execution_verdict="APPROVE", position_management_actions=(), realized_pnl=50.0, mae=-10.0,
        mfe=60.0, why_trade_happened="because", why_trade_skipped=None, rule_explanations=(),
        ai_explanation="because", replay_link=None, collected_at=T0,
    )


class TestAddAndGet(unittest.TestCase):
    def test_add_returns_true_for_new_record(self):
        store = TradeMemoryStore()
        self.assertTrue(store.add(_record("t1")))
        self.assertEqual(store.get("t1").trace_id, "t1")

    def test_add_returns_false_for_duplicate_trace_id(self):
        store = TradeMemoryStore()
        store.add(_record("t1"))
        self.assertFalse(store.add(_record("t1")))
        self.assertEqual(store.count, 1)

    def test_get_missing_returns_none(self):
        store = TradeMemoryStore()
        self.assertIsNone(store.get("nope"))


class TestFindBy(unittest.TestCase):
    def setUp(self):
        self.store = TradeMemoryStore()
        self.store.add(_record("t1", symbol="EURUSD", sessions=("LONDON",), market_regime="MARKUP", strategy_id="ORB"))
        self.store.add(_record("t2", symbol="GBPUSD", sessions=("NEW_YORK",), market_regime="MARKDOWN", strategy_id="RANGE"))
        self.store.add(_record("t3", symbol="EURUSD", sessions=("NEW_YORK",), market_regime="MARKUP", strategy_id="RANGE"))

    def test_filter_by_symbol(self):
        results = self.store.find_by(symbol="EURUSD")
        self.assertEqual({r.trace_id for r in results}, {"t1", "t3"})

    def test_filter_by_session(self):
        results = self.store.find_by(session="NEW_YORK")
        self.assertEqual({r.trace_id for r in results}, {"t2", "t3"})

    def test_filter_by_regime(self):
        results = self.store.find_by(market_regime="MARKDOWN")
        self.assertEqual({r.trace_id for r in results}, {"t2"})

    def test_filter_by_strategy(self):
        results = self.store.find_by(strategy_id="RANGE")
        self.assertEqual({r.trace_id for r in results}, {"t2", "t3"})

    def test_combined_filters(self):
        results = self.store.find_by(symbol="EURUSD", market_regime="MARKUP")
        self.assertEqual({r.trace_id for r in results}, {"t1", "t3"})

    def test_predicate_filter(self):
        results = self.store.find_by(predicate=lambda r: r.trace_id == "t2")
        self.assertEqual({r.trace_id for r in results}, {"t2"})

    def test_no_filters_returns_all(self):
        self.assertEqual(len(self.store.find_by()), 3)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_add(self):
        store = TradeMemoryStore()
        errors = []

        def _writer(n):
            try:
                for i in range(50):
                    store.add(_record(f"t-{n}-{i}"))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(store.count, 200)


if __name__ == "__main__":
    unittest.main()
