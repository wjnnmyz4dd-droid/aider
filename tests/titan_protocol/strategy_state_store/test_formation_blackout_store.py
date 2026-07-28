"""Tests for `FormationBlackoutStore` -- restart-safe, concurrency-safe
per-`(pair, range_start)` formation-time news-blackout observation
(ADR-035 §2/§14, Amendment 1, Phase 7). Exercises real temp-file-backed
persistence, never mocked except for the deliberate fault-injection
tests that force a persist/logging failure to verify containment --
mirroring `test_store.py`'s own conventions for `OrbQualificationStore`."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from titan_protocol.strategy_state_store import formation_blackout_store as formation_blackout_store_module
from titan_protocol.strategy_state_store.config import StrategyStateStoreConfig
from titan_protocol.strategy_state_store.formation_blackout_store import (
    CorruptFormationBlackoutStateError,
    FormationBlackoutStore,
)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class _BrokenLogger:
    """Mirrors `test_store.py`'s own `_BrokenLogger` precedent -- a
    logger whose own `.error()` raises, to prove
    `_safe_log_persist_failure()` never propagates that failure."""

    def error(self, *args, **kwargs):
        raise RuntimeError("logger itself is broken")


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "orb_formation_blackout.json"

    def _make_store(self) -> FormationBlackoutStore:
        return FormationBlackoutStore(StrategyStateStoreConfig(state_file=self.state_file))


class TestBootstrapOnFirstRun(_StoreTestCase):
    def test_missing_file_bootstraps_empty_state_no_error(self):
        store = self._make_store()
        self.assertFalse(store.was_blackout_observed("EURUSD", _utc(2026, 7, 10, 13, 0, 0)))

    def test_missing_file_does_not_create_the_file_until_first_true_observation(self):
        self._make_store()
        self.assertFalse(self.state_file.exists())


class TestRecordAndRead(_StoreTestCase):
    def test_unobserved_key_reads_false(self):
        store = self._make_store()
        self.assertFalse(store.was_blackout_observed("EURUSD", _utc(2026, 7, 10, 13, 0, 0)))

    def test_a_true_observation_is_read_back_as_true(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, True)
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))

    def test_a_false_observation_alone_reads_false(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, False)
        self.assertFalse(store.was_blackout_observed("EURUSD", range_start))

    def test_a_later_false_observation_does_not_clear_an_earlier_true_one(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, True)
        store.record_cycle_observation("EURUSD", range_start, False)
        store.record_cycle_observation("EURUSD", range_start, False)
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))

    def test_different_pair_is_independent(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, True)
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))
        self.assertFalse(store.was_blackout_observed("GBPUSD", range_start))

    def test_different_range_start_is_independent(self):
        store = self._make_store()
        store.record_cycle_observation("EURUSD", _utc(2026, 7, 10, 13, 0, 0), True)
        self.assertTrue(store.was_blackout_observed("EURUSD", _utc(2026, 7, 10, 13, 0, 0)))
        self.assertFalse(store.was_blackout_observed("EURUSD", _utc(2026, 7, 10, 14, 0, 0)))


class TestRestartSurvival(_StoreTestCase):
    def test_true_observation_survives_a_simulated_process_restart(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, True)
        restarted = self._make_store()
        self.assertTrue(restarted.was_blackout_observed("EURUSD", range_start))

    def test_clean_formation_survives_a_simulated_process_restart_as_false(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, False)
        restarted = self._make_store()
        self.assertFalse(restarted.was_blackout_observed("EURUSD", range_start))


class TestCorruptAndUnsupportedState(_StoreTestCase):
    def test_corrupt_file_with_no_backup_raises_corrupt_state_error_at_construction(self):
        self.state_file.write_text("not valid json {{{", encoding="utf-8")
        with self.assertRaises(CorruptFormationBlackoutStateError):
            self._make_store()

    def test_corrupt_primary_recovers_from_backup(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, True)  # first write -- no prior file to back up
        store.record_cycle_observation("GBPUSD", range_start, True)  # second write rotates the first to .bak
        self.state_file.write_text("not valid json {{{", encoding="utf-8")
        recovered = self._make_store()
        # The backup reflects state as of just before the second write.
        self.assertTrue(recovered.was_blackout_observed("EURUSD", range_start))
        self.assertFalse(recovered.was_blackout_observed("GBPUSD", range_start))

    def test_unsupported_schema_version_raises_corrupt_state_error_at_construction(self):
        self.state_file.write_text(json.dumps({"schema_version": 999, "entries": {}}), encoding="utf-8")
        with self.assertRaises(CorruptFormationBlackoutStateError):
            self._make_store()


class TestWriteFailureContainment(_StoreTestCase):
    def test_persist_failure_is_caught_and_the_in_memory_value_still_stands(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            store.record_cycle_observation("EURUSD", range_start, True)  # must not raise
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))

    def test_logging_failure_inside_the_persist_failure_handler_does_not_raise(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")), \
             mock.patch.object(formation_blackout_store_module, "_LOGGER", _BrokenLogger()):
            store.record_cycle_observation("EURUSD", range_start, True)  # must not raise
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))


class TestRestartDuplicationAfterFailedPersist(_StoreTestCase):
    """(Same narrow, disclosed residual risk class as
    `OrbQualificationStore`'s own -- ADR-035 §18.A) documents the known
    limitation as a tested fact, not a silent assumption. Narrower here
    than the lockout's own exposure (§P7): the observation is written
    every cycle throughout formation, so only a blackout that both
    starts and fully clears within a single failed-persist-to-restart
    window is at risk, not a single-shot loss."""

    def test_restart_immediately_after_a_failed_persist_may_lose_the_observation(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            store.record_cycle_observation("EURUSD", range_start, True)
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))  # in-memory still correct
        restarted = self._make_store()
        # The failed persist never reached disk -- restart reloads "not observed."
        self.assertFalse(restarted.was_blackout_observed("EURUSD", range_start))


class TestLaterWholeStateSelfHealing(_StoreTestCase):
    def test_a_later_successful_write_for_another_key_flushes_the_earlier_failed_observation(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            store.record_cycle_observation("EURUSD", range_start, True)
        store.record_cycle_observation("GBPUSD", range_start, True)
        on_disk = json.loads(self.state_file.read_text(encoding="utf-8"))
        eur_key = f"EURUSD|{range_start.isoformat()}"
        gbp_key = f"GBPUSD|{range_start.isoformat()}"
        self.assertTrue(on_disk["entries"][eur_key])
        self.assertTrue(on_disk["entries"][gbp_key])


class TestNoRedundantPersist(_StoreTestCase):
    """`record_cycle_observation()`'s own documented optimization: a
    cycle that does not change the recorded value never touches disk --
    the common, no-blackout-ever case never writes the file at all."""

    def test_repeated_false_observations_never_create_the_file(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        for _ in range(5):
            store.record_cycle_observation("EURUSD", range_start, False)
        self.assertFalse(self.state_file.exists())

    def test_repeated_true_observations_after_the_first_do_not_re_persist(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.record_cycle_observation("EURUSD", range_start, True)
        with mock.patch.object(store, "_persist", side_effect=AssertionError("must not persist again")):
            store.record_cycle_observation("EURUSD", range_start, True)
            store.record_cycle_observation("EURUSD", range_start, False)
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))


class TestConcurrency(_StoreTestCase):
    def test_concurrent_true_observations_for_the_same_key_all_converge_to_true(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)

        def worker():
            store.record_cycle_observation("EURUSD", range_start, True)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(store.was_blackout_observed("EURUSD", range_start))

    def test_concurrent_different_keys_all_record_independently(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)

        def worker(pair):
            store.record_cycle_observation(pair, range_start, True)

        pairs = [f"PAIR{i}" for i in range(10)]
        threads = [threading.Thread(target=worker, args=(p,)) for p in pairs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(store.was_blackout_observed(p, range_start) for p in pairs))


if __name__ == "__main__":
    unittest.main()
