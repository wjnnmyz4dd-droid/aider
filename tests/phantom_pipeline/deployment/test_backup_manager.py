"""BackupManager tests — checksummed backup/restore for configuration/
database/analytics/trade-history, integrity verification, and manifest
round-tripping. All against temporary directories only."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from phantom_pipeline.deployment.backup_manager import BackupManager
from phantom_pipeline.deployment.models import BackupTarget

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


class TestBackupConfiguration(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.mkdtemp()
        self.backup_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.backup_root, ignore_errors=True)
        self.manager = BackupManager(self.backup_root)

    def test_backs_up_and_checksums_a_config_file(self):
        config_path = os.path.join(self.source_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write('{"profile": "LIVE"}')

        records = self.manager.backup_configuration([config_path], T0)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].target, BackupTarget.CONFIGURATION)
        self.assertTrue(os.path.isfile(records[0].backup_path))
        self.assertTrue(self.manager.verify_integrity(records[0]))

    def test_skips_a_nonexistent_source_file(self):
        records = self.manager.backup_configuration([os.path.join(self.source_dir, "missing.json")], T0)
        self.assertEqual(records, ())


class TestBackupDatabase(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.mkdtemp()
        self.backup_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.backup_root, ignore_errors=True)
        self.manager = BackupManager(self.backup_root)

        self.db_path = os.path.join(self.source_dir, "phantom.db")
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)")
        conn.execute("INSERT INTO trades (symbol) VALUES ('EURUSD')")
        conn.commit()
        conn.close()

    def test_backs_up_sqlite_database_via_online_backup_api(self):
        records = self.manager.backup_database([self.db_path], T0)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].target, BackupTarget.DATABASE)
        backup_conn = sqlite3.connect(records[0].backup_path)
        rows = backup_conn.execute("SELECT symbol FROM trades").fetchall()
        backup_conn.close()
        self.assertEqual(rows, [("EURUSD",)])
        self.assertTrue(self.manager.verify_integrity(records[0]))


class TestRestore(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.mkdtemp()
        self.backup_root = tempfile.mkdtemp()
        self.restore_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.backup_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.restore_dir, ignore_errors=True)
        self.manager = BackupManager(self.backup_root)

    def test_restores_a_valid_backup(self):
        source_path = os.path.join(self.source_dir, "analytics.json")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write("analytics-data")
        record = self.manager.backup_analytics([source_path], T0)[0]

        destination = os.path.join(self.restore_dir, "restored-analytics.json")
        result = self.manager.restore(record, destination, T0)

        self.assertTrue(result.restored)
        with open(destination, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "analytics-data")

    def test_refuses_to_restore_a_corrupted_backup(self):
        source_path = os.path.join(self.source_dir, "trades.json")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write("trade-history-data")
        record = self.manager.backup_trade_history([source_path], T0)[0]

        # Corrupt the backup file after the fact.
        with open(record.backup_path, "w", encoding="utf-8") as handle:
            handle.write("tampered!")

        destination = os.path.join(self.restore_dir, "restored-trades.json")
        result = self.manager.restore(record, destination, T0)

        self.assertFalse(result.restored)
        self.assertIn("checksum mismatch", result.detail)
        self.assertFalse(os.path.exists(destination))

    def test_verify_integrity_false_for_missing_backup_file(self):
        source_path = os.path.join(self.source_dir, "config.json")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write("x")
        record = self.manager.backup_configuration([source_path], T0)[0]
        os.remove(record.backup_path)

        self.assertFalse(self.manager.verify_integrity(record))


class TestManifestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.mkdtemp()
        self.backup_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.backup_root, ignore_errors=True)
        self.manager = BackupManager(self.backup_root)

    def test_write_and_read_manifest_preserves_records(self):
        source_path = os.path.join(self.source_dir, "config.json")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write("x")
        records = self.manager.backup_configuration([source_path], T0)
        manifest = self.manager.create_manifest(records, T0)
        manifest_path = os.path.join(self.backup_root, "manifest.json")

        self.manager.write_manifest(manifest, manifest_path)
        reloaded = self.manager.read_manifest(manifest_path)

        self.assertEqual(len(reloaded.records), 1)
        self.assertEqual(reloaded.records[0].checksum, records[0].checksum)
        self.assertEqual(reloaded.records[0].target, BackupTarget.CONFIGURATION)


if __name__ == "__main__":
    unittest.main()
