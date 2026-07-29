"""Tests for `OpportunitySelectionEngine.evaluate_window()` (ADR-037
§4-§6): thin composition over `OpportunityWinnerStore.decide_once()` plus
metrics/logging -- winner/tie/empty-candidate outcomes and metrics
bookkeeping, and that a selector-internal exception propagates uncaught
(Runtime is the sole catch boundary, per the Plan's explicit design)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from titan_protocol.opportunity_selection_engine.config import OpportunitySelectionEngineConfig
from titan_protocol.opportunity_selection_engine.engine import OpportunitySelectionEngine
from titan_protocol.opportunity_selection_engine.metrics import OpportunitySelectionEngineMetrics
from titan_protocol.opportunity_selection_engine.models import OpportunityCandidate
from titan_protocol.opportunity_selection_engine.store import OpportunityWinnerStore
from titan_protocol.strategy_engine.models import SessionName, TradeIntent


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _candidate(pair: str, score: float) -> OpportunityCandidate:
    return OpportunityCandidate(pair=pair, score=score, trade_intent=TradeIntent.BUY)


class _EngineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = Path(self._tmpdir.name) / "opportunity_winners.json"
        self.store = OpportunityWinnerStore(self.state_file)
        self.metrics = OpportunitySelectionEngineMetrics()
        self.config = OpportunitySelectionEngineConfig(tie_tolerance=0.5)

    def _make_engine(self, duration_minutes: int = 30) -> OpportunitySelectionEngine:
        return OpportunitySelectionEngine(self.config, self.store, duration_minutes, metrics=self.metrics)


class TestWinnerOutcome(_EngineTestCase):
    def test_single_candidate_wins_and_metrics_record_scan_and_winner(self):
        engine = self._make_engine()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        outcome = engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), range_start)
        self.assertEqual(outcome.winner, "EURUSD")
        self.assertEqual(self.metrics.scan_count, 1)
        self.assertEqual(self.metrics.winner_count, 1)
        self.assertEqual(self.metrics.tie_count, 0)
        self.assertEqual(self.metrics.empty_candidate_set_count, 0)


class TestTieOutcome(_EngineTestCase):
    def test_tie_records_tie_metric_not_winner(self):
        engine = self._make_engine()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        outcome = engine.evaluate_window(
            range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.6)), range_start,
        )
        self.assertIsNone(outcome.winner)
        self.assertEqual(self.metrics.tie_count, 1)
        self.assertEqual(self.metrics.winner_count, 0)


class TestEmptyCandidatesOutcome(_EngineTestCase):
    def test_empty_candidates_records_empty_candidate_set_metric(self):
        engine = self._make_engine()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        outcome = engine.evaluate_window(range_start, SessionName.LONDON, (), range_start)
        self.assertIsNone(outcome.winner)
        self.assertEqual(self.metrics.empty_candidate_set_count, 1)
        self.assertEqual(self.metrics.tie_count, 0)


class TestNoMetricsCollaborator(_EngineTestCase):
    def test_engine_functions_without_a_metrics_collaborator(self):
        engine = OpportunitySelectionEngine(self.config, self.store, 30, metrics=None)
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        outcome = engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), range_start)
        self.assertEqual(outcome.winner, "EURUSD")


class TestDurationSourcedAtConstruction(_EngineTestCase):
    def test_stale_window_per_the_constructed_duration_yields_no_winner(self):
        engine = self._make_engine(duration_minutes=30)
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        far_future_now = _utc(2026, 7, 10, 9, 0, 0)
        outcome = engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), far_future_now)
        self.assertIsNone(outcome.winner)


class TestSelectorFailurePropagatesUncaught(_EngineTestCase):
    def test_store_exception_propagates_out_of_evaluate_window(self):
        """The engine deliberately does not catch exceptions from
        `decide_once()` -- Runtime's own per-window try/except is the
        sole catch boundary (Plan's explicit design, addressed in
        `run_cycle()`)."""
        engine = self._make_engine()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        with mock.patch.object(self.store, "decide_once", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), range_start)


if __name__ == "__main__":
    unittest.main()
