"""Tests for `InFlightCommandStore` -- restart-safe persistence of
InFlightCommandRegistry's minimal pair-level state (production-readiness
hardening, ADR-034 Amendment 9). Exercises real temp-file-backed
persistence, never mocked: round-trip, missing file, corruption +
backup recovery, schema mismatch, and atomic-write cleanup -- the same
technique already proven by
titan_protocol.compliance_state_store.store.ComplianceStateStore."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from titan_protocol.runtime.in_flight_commands import InFlightSnapshotEntry
from titan_protocol.runtime.in_flight_store import InFlightCommandStore, InFlightStoreConfig

_NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


class _StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = self.tmp_path / "in_flight_commands.json"
        self.store = InFlightCommandStore(InFlightStoreConfig(state_file=self.state_file))


class TestMissingFile(_StoreTestCase):
    def test_load_returns_empty_tuple_when_file_never_existed(self):
        self.assertEqual(self.store.load(), ())


class TestRoundTrip(_StoreTestCase):
    def test_save_then_load_round_trips_exactly(self):
        entries = (
            InFlightSnapshotEntry(pair="EURUSD", correlation_id="corr-1", state="in_flight", timestamp=_NOW),
            InFlightSnapshotEntry(pair="GBPUSD", correlation_id="corr-2", state="awaiting_position_confirmation", timestamp=_NOW),
        )
        self.store.save(entries)
        self.assertTrue(self.state_file.exists())
        loaded = self.store.load()
        self.assertEqual(set(loaded), set(entries))

    def test_save_with_no_entries_produces_an_empty_but_valid_file(self):
        self.store.save(())
        self.assertEqual(self.store.load(), ())

    def test_a_second_save_overwrites_rather_than_appends(self):
        self.store.save((InFlightSnapshotEntry(pair="EURUSD", correlation_id="corr-1", state="in_flight", timestamp=_NOW),))
        self.store.save((InFlightSnapshotEntry(pair="GBPUSD", correlation_id="corr-2", state="in_flight", timestamp=_NOW),))
        loaded = self.store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].pair, "GBPUSD")

    def test_no_temp_file_left_behind_after_a_successful_save(self):
        self.store.save((InFlightSnapshotEntry(pair="EURUSD", correlation_id="corr-1", state="in_flight", timestamp=_NOW),))
        leftovers = list(self.tmp_path.glob(".tmp-in-flight-state-*"))
        self.assertEqual(leftovers, [])


class TestCorruptionHandling(_StoreTestCase):
    def test_corrupted_primary_with_no_backup_returns_empty_not_raise(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text("{not valid json", encoding="utf-8")
        self.assertEqual(self.store.load(), ())

    def test_corrupted_primary_falls_back_to_valid_backup(self):
        good_entries = (InFlightSnapshotEntry(pair="EURUSD", correlation_id="corr-1", state="in_flight", timestamp=_NOW),)
        self.store.save(good_entries)
        # A second save rotates the first (good) file to .bak, then a
        # corrupted primary is written directly to simulate a crash
        # mid-write on the *next* save leaving a bad primary behind.
        self.store.save((InFlightSnapshotEntry(pair="GBPUSD", correlation_id="corr-2", state="in_flight", timestamp=_NOW),))
        self.state_file.write_text("{not valid json", encoding="utf-8")
        loaded = self.store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].pair, "EURUSD")

    def test_corrupted_primary_and_corrupted_backup_returns_empty(self):
        self.store.save((InFlightSnapshotEntry(pair="EURUSD", correlation_id="corr-1", state="in_flight", timestamp=_NOW),))
        self.state_file.write_text("{not valid json", encoding="utf-8")
        backup = self.state_file.with_suffix(self.state_file.suffix + ".bak")
        backup.write_text("{also not valid json", encoding="utf-8")
        self.assertEqual(self.store.load(), ())

    def test_schema_version_mismatch_is_treated_as_corrupt(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"schema_version": 999, "entries": []}), encoding="utf-8")
        self.assertEqual(self.store.load(), ())

    def test_missing_entries_key_is_treated_as_corrupt_not_a_crash(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        self.assertEqual(self.store.load(), ())

    def test_malformed_entry_missing_a_required_field_is_treated_as_corrupt(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps({"schema_version": 1, "entries": [{"pair": "EURUSD"}]}), encoding="utf-8",
        )
        self.assertEqual(self.store.load(), ())


if __name__ == "__main__":
    unittest.main()
