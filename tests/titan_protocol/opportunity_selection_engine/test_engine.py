"""Tests for `OpportunitySelectionEngine.evaluate_window()` (ADR-037
§4-§6): thin composition over `OpportunityWinnerStore.decide_once()` plus
metrics/logging -- winner/tie/empty-candidate outcomes and metrics
bookkeeping, and that a selector-internal exception propagates uncaught
(Runtime is the sole catch boundary, per the Plan's explicit design).

Post-implementation conformance re-review correction (`254e9d6`..this
commit): the constructor no longer takes `opening_range_duration_minutes`
(the store no longer needs it -- see `store.py`'s docstring); this engine
now owns a best-effort, in-memory "genuinely superseded opportunity"
observability signal instead (ADR-037 §12, corrected)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def _make_engine(self) -> OpportunitySelectionEngine:
        return OpportunitySelectionEngine(self.config, self.store, metrics=self.metrics)


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
        engine = OpportunitySelectionEngine(self.config, self.store, metrics=None)
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        outcome = engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), range_start)
        self.assertEqual(outcome.winner, "EURUSD")


class TestRealisticPostFormationWinnerSelection(_EngineTestCase):
    """Post-implementation conformance re-review correction: a genuine
    candidate at a realistic post-formation `now` (not `now == range_
    start`) must select and persist a winner -- this is exactly the
    scenario the removed duration-based staleness gate used to suppress."""

    def test_far_future_now_still_selects_a_winner(self):
        engine = self._make_engine()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        far_future_now = _utc(2026, 7, 10, 9, 0, 0)  # 2 hours past range_start
        outcome = engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), far_future_now)
        self.assertEqual(outcome.winner, "EURUSD")


class TestSupersededOpportunityObservability(_EngineTestCase):
    """ADR-037 §12's "stale winner" signal, corrected (SS9/Amendment 1
    forbid deriving it from elapsed formation duration): fires only when
    a genuinely older `range_start` is queried, for the same
    `session_name`, after a newer one has already been current -- and
    never changes the actual outcome or gates `decide_once()`."""

    def test_older_range_start_after_a_newer_one_logs_but_does_not_suppress(self):
        engine = self._make_engine()
        newer = _utc(2026, 7, 11, 13, 0, 0)
        older = _utc(2026, 7, 10, 13, 0, 0)

        engine.evaluate_window(newer, SessionName.LONDON, (_candidate("GBPUSD", 50.0),), newer)

        with self.assertLogs("titan_protocol.opportunity_selection_engine", level="WARNING") as logs:
            outcome = engine.evaluate_window(older, SessionName.LONDON, (_candidate("EURUSD", 80.0),), older)

        # Never suppressed: the older range_start still gets its own,
        # independent, genuine decision.
        self.assertEqual(outcome.winner, "EURUSD")
        self.assertTrue(
            any("superseded_opportunity_window_encountered" in line for line in logs.output),
            f"expected the corrected SS12 signal in logs, got: {logs.output}",
        )

    def test_same_or_newer_range_start_never_logs_superseded(self):
        engine = self._make_engine()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        engine.evaluate_window(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), range_start)

        logger = __import__("logging").getLogger("titan_protocol.opportunity_selection_engine")
        with mock.patch.object(logger, "warning") as warning_mock:
            later_same_day = range_start + timedelta(hours=1)
            engine.evaluate_window(later_same_day, SessionName.LONDON, (_candidate("GBPUSD", 50.0),), later_same_day)
        warning_mock.assert_not_called()

    def test_different_session_names_are_tracked_independently(self):
        engine = self._make_engine()
        newer_ny = _utc(2026, 7, 10, 17, 0, 0)
        older_london = _utc(2026, 7, 10, 7, 0, 0)
        engine.evaluate_window(newer_ny, SessionName.LATE_NEW_YORK, (_candidate("EURUSD", 80.0),), newer_ny)

        logger = __import__("logging").getLogger("titan_protocol.opportunity_selection_engine")
        with mock.patch.object(logger, "warning") as warning_mock:
            # An older range_start, but for a *different* session -- must
            # not be conflated with LATE_NEW_YORK's own high-water-mark.
            engine.evaluate_window(older_london, SessionName.LONDON, (_candidate("GBPUSD", 50.0),), older_london)
        warning_mock.assert_not_called()


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
