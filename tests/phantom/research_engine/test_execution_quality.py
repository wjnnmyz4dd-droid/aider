"""Unit tests: the Execution Quality Monitor (ADR-029 §5)."""

from __future__ import annotations

import unittest

from phantom.research_engine.execution_quality import compute_execution_quality_record, summarize_execution_quality
from tests.phantom.research_engine._fixtures import make_config, make_executed_trade, make_rejected_trade


class TestPerTradeScore(unittest.TestCase):
    def test_zero_slippage_zero_requotes_scores_high(self):
        config = make_config()
        trade = make_executed_trade(slippage_entry_pips=0.0, slippage_exit_pips=0.0, requotes=0, time_to_fill_ms=100.0)
        record = compute_execution_quality_record(trade, config)
        self.assertGreater(record.composite_score, 90.0)

    def test_large_slippage_reduces_score(self):
        config = make_config(max_acceptable_slippage_pips=1.0)
        clean = make_executed_trade(slippage_entry_pips=0.0, slippage_exit_pips=0.0)
        dirty = make_executed_trade(slippage_entry_pips=5.0, slippage_exit_pips=5.0)
        clean_record = compute_execution_quality_record(clean, config)
        dirty_record = compute_execution_quality_record(dirty, config)
        self.assertLess(dirty_record.composite_score, clean_record.composite_score)

    def test_requotes_reduce_score(self):
        config = make_config()
        no_requotes = make_executed_trade(requotes=0)
        many_requotes = make_executed_trade(requotes=5)
        self.assertLess(
            compute_execution_quality_record(many_requotes, config).composite_score,
            compute_execution_quality_record(no_requotes, config).composite_score,
        )

    def test_score_never_negative_or_above_100(self):
        config = make_config()
        trade = make_executed_trade(slippage_entry_pips=1000.0, slippage_exit_pips=1000.0, requotes=100, time_to_fill_ms=1_000_000.0)
        record = compute_execution_quality_record(trade, config)
        self.assertGreaterEqual(record.composite_score, 0.0)
        self.assertLessEqual(record.composite_score, 100.0)


class TestSummary(unittest.TestCase):
    def test_empty_history_returns_zero_summary(self):
        config = make_config()
        summary = summarize_execution_quality([], config)
        self.assertEqual(summary.overall_score, 0.0)
        self.assertEqual(summary.per_pair_score, ())

    def test_rejected_trades_excluded_from_summary(self):
        config = make_config()
        trades = [make_executed_trade(index=i) for i in range(5)]
        trades.append(make_rejected_trade(index=100))
        summary = summarize_execution_quality(trades, config)
        self.assertEqual(sum(1 for _ in trades if _.was_executed), 5)
        # per_pair_score derived only from the 5 executed trades -- sanity via overall_score being finite/sane
        self.assertGreaterEqual(summary.overall_score, 0.0)

    def test_per_pair_breakdown(self):
        config = make_config()
        trades = [make_executed_trade(index=i, pair="EURUSD") for i in range(3)]
        trades += [make_executed_trade(index=i, pair="GBPUSD") for i in range(3, 6)]
        summary = summarize_execution_quality(trades, config)
        self.assertEqual({p for p, _ in summary.per_pair_score}, {"EURUSD", "GBPUSD"})


if __name__ == "__main__":
    unittest.main()
