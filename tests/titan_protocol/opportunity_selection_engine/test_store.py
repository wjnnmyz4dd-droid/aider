"""Tests for `OpportunityWinnerStore` -- winner-only durable persistence
(ADR-037 §9, as corrected by Amendment 1). Exercises real temp-file-backed
persistence; mocks only for the deliberate fault-injection tests.

Post-implementation conformance re-review correction (`254e9d6`..this
commit): `decide_once()` no longer takes a `duration_minutes` parameter
and performs no time-based staleness computation at all (see
`store.py`'s module docstring for the full rationale). Several tests
below deliberately use `now` values meaningfully past `range_start` --
not merely `now == range_start` -- since that is what every genuine ORB
candidate looks like in production (`orb_breakout.py`'s own `is_formed`
gate requires `now >= range_start + opening_range_duration_minutes`
before a candidate can exist at all); the old suite never exercised this
realistic relationship, which is exactly how the removed defect went
undetected."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from titan_protocol.opportunity_selection_engine import store as store_module
from titan_protocol.opportunity_selection_engine.models import (
    CorruptOpportunityWinnerStateError,
    OpportunityCandidate,
)
from titan_protocol.opportunity_selection_engine.store import OpportunityWinnerStore
from titan_protocol.strategy_engine.models import SessionName, TradeIntent


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _candidate(pair: str, score: float) -> OpportunityCandidate:
    return OpportunityCandidate(pair=pair, score=score, trade_intent=TradeIntent.BUY)


class _BrokenLogger:
    def error(self, *args, **kwargs):
        raise RuntimeError("logger itself is broken")

    def warning(self, *args, **kwargs):
        raise RuntimeError("logger itself is broken")


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "opportunity_winners.json"

    def _make_store(self) -> OpportunityWinnerStore:
        return OpportunityWinnerStore(self.state_file)


class TestBootstrapOnFirstRun(_StoreTestCase):
    def test_missing_file_bootstraps_empty_state_no_error(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        self.assertEqual(winner, "EURUSD")

    def test_missing_file_does_not_create_the_file_until_first_genuine_winner(self):
        self._make_store()
        self.assertFalse(self.state_file.exists())


class TestZeroCandidatesNeverPersists(_StoreTestCase):
    def test_zero_candidates_returns_none_and_writes_no_file(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        winner = store.decide_once(range_start, SessionName.LONDON, (), 0.5, range_start)
        self.assertIsNone(winner)
        self.assertFalse(self.state_file.exists())

    def test_tie_returns_none_and_writes_no_file(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        winner = store.decide_once(
            range_start, SessionName.LONDON,
            (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.6)), 0.5, range_start,
        )
        self.assertIsNone(winner)
        self.assertFalse(self.state_file.exists())


class TestGenuineWinnerPersists(_StoreTestCase):
    def test_single_candidate_persists_a_winner(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        self.assertEqual(winner, "EURUSD")
        self.assertTrue(self.state_file.exists())
        on_disk = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["entries"][range_start.isoformat()]["pair"], "EURUSD")


class TestWinnerImmutability(_StoreTestCase):
    def test_later_higher_scoring_candidate_cannot_replace_the_persisted_winner(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        first = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 60.0),), 0.5, range_start)
        self.assertEqual(first, "EURUSD")
        second = store.decide_once(range_start, SessionName.LONDON, (_candidate("GBPUSD", 99.0),), 0.5, range_start)
        self.assertEqual(second, "EURUSD")

    def test_zero_candidates_then_later_winner_succeeds(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        first = store.decide_once(range_start, SessionName.LONDON, (), 0.5, range_start)
        self.assertIsNone(first)
        second = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        self.assertEqual(second, "EURUSD")

    def test_tie_then_later_winner_succeeds(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        first = store.decide_once(
            range_start, SessionName.LONDON,
            (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.6)), 0.5, range_start,
        )
        self.assertIsNone(first)
        second = store.decide_once(range_start, SessionName.LONDON, (_candidate("USDJPY", 90.0),), 0.5, range_start)
        self.assertEqual(second, "USDJPY")

    def test_sequential_same_window_multi_cycle_invocation_converges_once(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        results = []
        for score in (10.0, 20.0, 30.0):
            results.append(
                store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", score),), 0.5, range_start)
            )
        self.assertEqual(results, ["EURUSD", "EURUSD", "EURUSD"])


class TestRestartSurvival(_StoreTestCase):
    def test_winner_survives_a_simulated_process_restart(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        restarted = self._make_store()
        winner = restarted.decide_once(range_start, SessionName.LONDON, (_candidate("GBPUSD", 99.0),), 0.5, range_start)
        self.assertEqual(winner, "EURUSD")

    def test_no_winner_yet_established_state_survives_restart_and_remains_recomputable(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        store.decide_once(range_start, SessionName.LONDON, (), 0.5, range_start)
        restarted = self._make_store()
        winner = restarted.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        self.assertEqual(winner, "EURUSD")

    def test_winner_established_at_realistic_post_formation_time_survives_restart(self):
        """Regression proof (required scenario 7): a winner decided at a
        realistic post-formation `now` -- not `now == range_start` -- must
        still be intact and immutable after a simulated restart."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        formation_complete = range_start + timedelta(minutes=31)
        store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, formation_complete)
        restarted = self._make_store()
        much_later = range_start + timedelta(hours=6)
        winner = restarted.decide_once(range_start, SessionName.LONDON, (_candidate("GBPUSD", 99.0),), 0.5, much_later)
        self.assertEqual(winner, "EURUSD")


class TestDifferentRangeStartIsIndependent(_StoreTestCase):
    def test_different_range_start_gets_its_own_winner(self):
        store = self._make_store()
        r1 = _utc(2026, 7, 10, 7, 0, 0)
        r2 = _utc(2026, 7, 10, 8, 0, 0)
        w1 = store.decide_once(r1, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, r1)
        w2 = store.decide_once(r2, SessionName.LONDON, (_candidate("GBPUSD", 80.0),), 0.5, r2)
        self.assertEqual(w1, "EURUSD")
        self.assertEqual(w2, "GBPUSD")

    def test_a_newer_range_start_for_the_same_anchor_never_inherits_the_older_winner(self):
        """Regression proof (required scenario 6): once a newer opportunity
        `range_start` (e.g. the next calendar day's instance of the same
        anchor) becomes current, it gets an entirely independent decision
        -- the older key's persisted winner never leaks into it, since
        each calendar day's `range_start` is, by construction, a distinct
        key (ADR-037 §8)."""
        store = self._make_store()
        yesterday = _utc(2026, 7, 10, 13, 0, 0)
        today = _utc(2026, 7, 11, 13, 0, 0)
        store.decide_once(yesterday, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, yesterday + timedelta(minutes=31))
        winner_today = store.decide_once(today, SessionName.LONDON, (_candidate("GBPUSD", 50.0),), 0.5, today + timedelta(minutes=31))
        self.assertEqual(winner_today, "GBPUSD")
        # The old day's own entry remains, untouched and independently immutable.
        winner_yesterday_again = store.decide_once(
            yesterday, SessionName.LONDON, (_candidate("USDJPY", 999.0),), 0.5, yesterday + timedelta(hours=5),
        )
        self.assertEqual(winner_yesterday_again, "EURUSD")


class TestRealisticPostFormationTiming(_StoreTestCase):
    """Post-implementation conformance re-review correction: the removed
    duration-based staleness gate suppressed essentially every realistic
    candidate, since ORB only ever qualifies once `now >= range_start +
    opening_range_duration_minutes` (`orb_breakout.py`'s own `is_formed`
    gate). These tests use `now` values that reflect that reality instead
    of the old suite's `now == range_start` convention."""

    def test_now_one_minute_past_formation_completion_selects_and_persists_a_winner(self):
        """Required scenario 1: now = range_end + 1 minute, valid
        candidate -> winner selected and persisted."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        opening_range_duration_minutes = 30
        now = range_start + timedelta(minutes=opening_range_duration_minutes + 1)
        winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, now)
        self.assertEqual(winner, "EURUSD")
        self.assertTrue(self.state_file.exists())

    def test_now_exactly_at_formation_completion_boundary_selects_a_winner(self):
        """Required scenario 2: exact range_end boundary -> valid
        behavior (a winner is genuinely selected, not treated as an edge
        case to reject)."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        now = range_start + timedelta(minutes=30)  # now == range_end exactly
        winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, now)
        self.assertEqual(winner, "EURUSD")

    def test_persisted_winner_queried_much_later_still_returns_the_same_winner(self):
        """Required scenario 3: persisted winner queried one second/minute
        later -> same winner returned. Exercised well beyond a minute to
        prove there is no hidden decay window at all."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        first_now = range_start + timedelta(minutes=31)
        winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, first_now)
        self.assertEqual(winner, "EURUSD")

        for delta in (timedelta(seconds=1), timedelta(minutes=1), timedelta(hours=1), timedelta(hours=8)):
            later_now = range_start + timedelta(minutes=31) + delta
            later_winner = store.decide_once(
                range_start, SessionName.LONDON, (_candidate("GBPUSD", 999.0),), 0.5, later_now,
            )
            self.assertEqual(later_winner, "EURUSD", f"winner masked/replaced after {delta} elapsed")

    def test_zero_candidates_after_formation_then_later_candidate_with_same_range_start_wins(self):
        """Required scenario 4: zero candidates after formation -> later
        candidate with the same range_start wins."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        first = store.decide_once(range_start, SessionName.LONDON, (), 0.5, range_start + timedelta(minutes=31))
        self.assertIsNone(first)
        second = store.decide_once(
            range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start + timedelta(minutes=90),
        )
        self.assertEqual(second, "EURUSD")

    def test_tie_after_formation_then_later_unique_candidate_wins(self):
        """Required scenario 5: tie after formation -> later unique
        candidate wins."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        first = store.decide_once(
            range_start, SessionName.LONDON,
            (_candidate("EURUSD", 80.0), _candidate("GBPUSD", 79.6)), 0.5, range_start + timedelta(minutes=31),
        )
        self.assertIsNone(first)
        second = store.decide_once(
            range_start, SessionName.LONDON, (_candidate("USDJPY", 90.0),), 0.5, range_start + timedelta(minutes=90),
        )
        self.assertEqual(second, "USDJPY")


class TestCorruptAndUnsupportedState(_StoreTestCase):
    def test_corrupt_file_with_no_backup_raises_at_construction(self):
        self.state_file.write_text("not valid json {{{", encoding="utf-8")
        with self.assertRaises(CorruptOpportunityWinnerStateError):
            self._make_store()

    def test_corrupt_primary_recovers_from_backup(self):
        store = self._make_store()
        r1 = _utc(2026, 7, 10, 7, 0, 0)
        r2 = _utc(2026, 7, 10, 8, 0, 0)
        store.decide_once(r1, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, r1)  # first write, no backup yet
        store.decide_once(r2, SessionName.LONDON, (_candidate("GBPUSD", 80.0),), 0.5, r2)  # rotates first to .bak
        self.state_file.write_text("not valid json {{{", encoding="utf-8")
        recovered = self._make_store()
        # backup reflects state as of just before the second write: only r1's entry.
        winner_r1 = recovered.decide_once(r1, SessionName.LONDON, (_candidate("USDJPY", 99.0),), 0.5, r1)
        self.assertEqual(winner_r1, "EURUSD")

    def test_unsupported_schema_version_raises_at_construction(self):
        self.state_file.write_text(json.dumps({"schema_version": 999, "entries": {}}), encoding="utf-8")
        with self.assertRaises(CorruptOpportunityWinnerStateError):
            self._make_store()

    def test_malformed_entry_missing_pair_raises_at_construction(self):
        self.state_file.write_text(
            json.dumps({"schema_version": 1, "entries": {"x": {"session_name": "LONDON"}}}), encoding="utf-8"
        )
        with self.assertRaises(CorruptOpportunityWinnerStateError):
            self._make_store()


class TestWriteFailureContainment(_StoreTestCase):
    def test_persist_failure_is_caught_and_winner_still_returned(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        self.assertEqual(winner, "EURUSD")

    def test_logging_failure_inside_the_persist_failure_handler_does_not_raise(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")), \
             mock.patch.object(store_module, "_LOGGER", _BrokenLogger()):
            winner = store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        self.assertEqual(winner, "EURUSD")

    def test_in_memory_winner_still_immutable_after_a_failed_persist(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            store.decide_once(range_start, SessionName.LONDON, (_candidate("EURUSD", 80.0),), 0.5, range_start)
        second = store.decide_once(range_start, SessionName.LONDON, (_candidate("GBPUSD", 99.0),), 0.5, range_start)
        self.assertEqual(second, "EURUSD")


class TestConcurrency(_StoreTestCase):
    def test_concurrent_differing_candidate_sets_converge_on_exactly_one_winner(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 7, 0, 0)
        results = []
        results_lock = threading.Lock()

        def worker(pair, score):
            result = store.decide_once(range_start, SessionName.LONDON, (_candidate(pair, score),), 0.5, range_start)
            with results_lock:
                results.append(result)

        pairs = [(f"PAIR{i}", float(i)) for i in range(20)]
        threads = [threading.Thread(target=worker, args=pair) for pair in pairs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        distinct_winners = set(results)
        self.assertEqual(len(distinct_winners), 1, f"expected exactly one converged winner, got {distinct_winners}")

    def test_concurrent_different_range_starts_are_independent(self):
        store = self._make_store()
        results = {}
        results_lock = threading.Lock()

        def worker(hour):
            range_start = _utc(2026, 7, 10, hour, 0, 0)
            result = store.decide_once(range_start, SessionName.LONDON, (_candidate(f"PAIR{hour}", 50.0),), 0.5, range_start)
            with results_lock:
                results[hour] = result

        threads = [threading.Thread(target=worker, args=(h,)) for h in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for hour in range(5):
            self.assertEqual(results[hour], f"PAIR{hour}")

    def test_concurrent_differing_candidate_sets_at_realistic_post_formation_time_still_converge(self):
        """Required scenario 8: competing concurrent candidate sets, at a
        realistic post-formation `now`, still converge on exactly one
        durable winner."""
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        now = range_start + timedelta(minutes=31)
        results = []
        results_lock = threading.Lock()

        def worker(pair, score):
            result = store.decide_once(range_start, SessionName.LONDON, (_candidate(pair, score),), 0.5, now)
            with results_lock:
                results.append(result)

        pairs = [(f"PAIR{i}", float(i)) for i in range(20)]
        threads = [threading.Thread(target=worker, args=pair) for pair in pairs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        distinct_winners = set(results)
        self.assertEqual(len(distinct_winners), 1, f"expected exactly one converged winner, got {distinct_winners}")


if __name__ == "__main__":
    unittest.main()
