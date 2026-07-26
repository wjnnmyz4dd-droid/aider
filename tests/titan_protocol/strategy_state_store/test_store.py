"""Tests for `OrbQualificationStore` -- restart-safe, concurrency-safe
per-`(pair, range_start)` ORB qualification lockout (ADR-035 §18.A item
2, Phase 2 Step 2B). Exercises real temp-file-backed persistence, never
mocked except for the deliberate fault-injection tests that force a
persist/logging failure to verify containment."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from titan_protocol.strategy_state_store import store as store_module
from titan_protocol.strategy_state_store.config import StrategyStateStoreConfig
from titan_protocol.strategy_state_store.models import CorruptStateError
from titan_protocol.strategy_state_store.store import OrbQualificationStore


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class _BrokenLogger:
    """Mirrors the `_BrokenLogger` precedent in
    `tests/deployment_windows/test_positions_staleness_observability.py`
    -- a logger whose own `.error()` raises, to prove
    `_safe_log_persist_failure()` never propagates that failure."""

    def error(self, *args, **kwargs):
        raise RuntimeError("logger itself is broken")


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "orb_state.json"

    def _make_store(self) -> OrbQualificationStore:
        return OrbQualificationStore(StrategyStateStoreConfig(state_file=self.state_file))


class TestBootstrapOnFirstRun(_StoreTestCase):
    def test_missing_file_bootstraps_empty_state_no_error(self):
        store = self._make_store()
        self.assertTrue(store.try_consume("EURUSD", _utc(2026, 7, 10, 13, 0, 0), 1))

    def test_missing_file_does_not_create_the_file_until_first_consume(self):
        self._make_store()
        self.assertFalse(self.state_file.exists())


class TestFirstConsumeAndLimit(_StoreTestCase):
    def test_first_consume_succeeds(self):
        store = self._make_store()
        self.assertTrue(store.try_consume("EURUSD", _utc(2026, 7, 10, 13, 0, 0), 1))

    def test_limit_reached_denies_further_consumption(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        self.assertTrue(store.try_consume("EURUSD", range_start, 1))
        self.assertFalse(store.try_consume("EURUSD", range_start, 1))

    def test_different_pair_is_independent(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        self.assertTrue(store.try_consume("EURUSD", range_start, 1))
        self.assertTrue(store.try_consume("GBPUSD", range_start, 1))

    def test_different_range_start_is_independent(self):
        store = self._make_store()
        self.assertTrue(store.try_consume("EURUSD", _utc(2026, 7, 10, 13, 0, 0), 1))
        self.assertTrue(store.try_consume("EURUSD", _utc(2026, 7, 10, 14, 0, 0), 1))

    def test_max_allowed_greater_than_one_permits_n_then_denies(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        self.assertTrue(store.try_consume("EURUSD", range_start, 2))
        self.assertTrue(store.try_consume("EURUSD", range_start, 2))
        self.assertFalse(store.try_consume("EURUSD", range_start, 2))


class TestRestartSurvival(_StoreTestCase):
    def test_state_survives_a_simulated_process_restart(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        self.assertTrue(store.try_consume("EURUSD", range_start, 1))
        restarted = self._make_store()
        self.assertFalse(restarted.try_consume("EURUSD", range_start, 1))


class TestCorruptAndUnsupportedState(_StoreTestCase):
    def test_corrupt_file_with_no_backup_raises_corrupt_state_error_at_construction(self):
        self.state_file.write_text("not valid json {{{", encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            self._make_store()

    def test_corrupt_primary_recovers_from_backup(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        store.try_consume("EURUSD", range_start, 5)  # first write -- no prior file to back up
        store.try_consume("EURUSD", range_start, 5)  # second write rotates the first to .bak
        self.state_file.write_text("not valid json {{{", encoding="utf-8")
        recovered = self._make_store()
        # The backup reflects state as of just before the second write
        # (count=1), not the corrupted primary's would-be count=2.
        self.assertFalse(recovered.try_consume("EURUSD", range_start, 1))

    def test_unsupported_schema_version_raises_corrupt_state_error_at_construction(self):
        self.state_file.write_text(json.dumps({"schema_version": 999, "entries": {}}), encoding="utf-8")
        with self.assertRaises(CorruptStateError):
            self._make_store()


class TestWriteFailureContainment(_StoreTestCase):
    def test_persist_failure_is_caught_and_try_consume_still_returns_true(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            result = store.try_consume("EURUSD", range_start, 1)
        self.assertTrue(result)

    def test_logging_failure_inside_the_persist_failure_handler_does_not_raise(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")), \
             mock.patch.object(store_module, "_LOGGER", _BrokenLogger()):
            result = store.try_consume("EURUSD", range_start, 1)
        self.assertTrue(result)

    def test_same_process_second_attempt_after_failed_persist_still_sees_consumed_count(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            store.try_consume("EURUSD", range_start, 1)
        # No mock this time -- the in-memory dict, not the disk, is authoritative.
        self.assertFalse(store.try_consume("EURUSD", range_start, 1))


class TestRestartDuplicationAfterFailedPersist(_StoreTestCase):
    """(ADR-035 §18.A-accepted residual risk) documents the known,
    narrow limitation as a tested fact, not a silent assumption."""

    def test_restart_after_a_failed_persist_may_reload_the_stale_count(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            self.assertTrue(store.try_consume("EURUSD", range_start, 1))
        restarted = self._make_store()
        self.assertTrue(restarted.try_consume("EURUSD", range_start, 1))


class TestLaterWholeStateSelfHealing(_StoreTestCase):
    def test_a_later_successful_write_for_another_key_flushes_the_earlier_failed_increment(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        with mock.patch.object(store, "_persist", side_effect=OSError("simulated disk failure")):
            self.assertTrue(store.try_consume("EURUSD", range_start, 1))
        self.assertTrue(store.try_consume("GBPUSD", range_start, 1))
        on_disk = json.loads(self.state_file.read_text(encoding="utf-8"))
        eur_key = f"EURUSD|{range_start.isoformat()}"
        gbp_key = f"GBPUSD|{range_start.isoformat()}"
        self.assertEqual(on_disk["entries"][eur_key], 1)
        self.assertEqual(on_disk["entries"][gbp_key], 1)


class TestConcurrency(_StoreTestCase):
    def test_concurrent_same_key_max_allowed_one_produces_exactly_one_success(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        results = []
        results_lock = threading.Lock()

        def worker():
            result = store.try_consume("EURUSD", range_start, 1)
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 9)

    def test_concurrent_different_keys_all_succeed_independently(self):
        store = self._make_store()
        range_start = _utc(2026, 7, 10, 13, 0, 0)
        results = []
        results_lock = threading.Lock()

        def worker(pair):
            result = store.try_consume(pair, range_start, 1)
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=worker, args=(f"PAIR{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(results))


if __name__ == "__main__":
    unittest.main()
