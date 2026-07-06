"""Production logging tests — JSON formatting, rotation config, daily
archival, crash-dump generation, retention-policy enforcement. All
against temporary directories only."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from phantom_pipeline.deployment.logging_manager import (
    archive_daily_logs,
    configure_production_logging,
    enforce_retention_policy,
    generate_crash_dump,
)

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


class TestConfigureProductionLogging(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def test_writes_valid_json_lines(self):
        logger = configure_production_logging("phantom.test_logger", self.tmp_dir)
        logger.info("hello world")
        for handler in list(logger.handlers):
            handler.flush()
            handler.close()
            logger.removeHandler(handler)

        log_path = os.path.join(self.tmp_dir, "phantom.test_logger.log")
        with open(log_path, "r", encoding="utf-8") as handle:
            lines = [line for line in handle if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["level"], "INFO")


class TestArchiveDailyLogs(unittest.TestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp()
        self.archive_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.log_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.archive_dir, ignore_errors=True)

    def test_archives_and_truncates_non_empty_logs(self):
        log_path = os.path.join(self.log_dir, "app.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("line one\nline two\n")

        archived = archive_daily_logs(self.log_dir, self.archive_dir, T0)

        self.assertEqual(len(archived), 1)
        with gzip.open(archived[0], "rt", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "line one\nline two\n")
        self.assertEqual(os.path.getsize(log_path), 0)

    def test_skips_empty_logs(self):
        open(os.path.join(self.log_dir, "empty.log"), "w").close()
        archived = archive_daily_logs(self.log_dir, self.archive_dir, T0)
        self.assertEqual(archived, ())


class TestGenerateCrashDump(unittest.TestCase):
    def setUp(self):
        self.dump_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dump_dir, ignore_errors=True)

    def test_writes_structured_crash_dump(self):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            path = generate_crash_dump("mt5_bridge", exc, self.dump_dir, T0, context={"component": "mt5"})

        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["component"], "mt5_bridge")
        self.assertEqual(payload["exception_type"], "ValueError")
        self.assertIn("boom", payload["exception_message"])
        self.assertIn("Traceback", payload["traceback"])
        self.assertEqual(payload["context"]["component"], "mt5")


class TestEnforceRetentionPolicy(unittest.TestCase):
    def setUp(self):
        self.archive_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.archive_dir, ignore_errors=True)

    def test_deletes_files_older_than_retention_and_keeps_recent_ones(self):
        old_path = os.path.join(self.archive_dir, "old.log.gz")
        recent_path = os.path.join(self.archive_dir, "recent.log.gz")
        open(old_path, "w").close()
        open(recent_path, "w").close()

        old_time = (T0 - timedelta(days=40)).timestamp()
        os.utime(old_path, (old_time, old_time))

        removed = enforce_retention_policy(self.archive_dir, retention_days=30, now=T0)

        self.assertEqual(removed, (old_path,))
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(recent_path))

    def test_missing_archive_dir_returns_empty(self):
        removed = enforce_retention_policy(os.path.join(self.archive_dir, "does-not-exist"), 30, T0)
        self.assertEqual(removed, ())


if __name__ == "__main__":
    unittest.main()
