"""Session facts (ADR-002 §5), including the naive-timestamp edge case
that `quality.py` treats as §9's "clock/session ambiguity" failure mode."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.scanner.config import ScannerConfig, SessionWindow
from phantom_pipeline.scanner.session import compute_session


class TestSessionWindows(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig()

    def test_active_session_detected(self):
        # LONDON is 07:00-16:00 UTC in the default config.
        session_time = datetime(2026, 7, 4, 10, 0, 0, tzinfo=timezone.utc)
        state = compute_session(session_time, self.config)
        self.assertIn("LONDON", state.active_sessions)

    def test_multiple_overlapping_sessions_all_reported(self):
        # LONDON (07-16) and NEW_YORK (12-21) overlap at 13:00 UTC.
        session_time = datetime(2026, 7, 4, 13, 0, 0, tzinfo=timezone.utc)
        state = compute_session(session_time, self.config)
        self.assertIn("LONDON", state.active_sessions)
        self.assertIn("NEW_YORK", state.active_sessions)

    def test_wraparound_window_handles_midnight_crossing(self):
        # SYDNEY is 21:00-06:00 UTC — active at 23:00 and at 02:00.
        late = datetime(2026, 7, 4, 23, 0, 0, tzinfo=timezone.utc)
        early = datetime(2026, 7, 4, 2, 0, 0, tzinfo=timezone.utc)
        self.assertIn("SYDNEY", compute_session(late, self.config).active_sessions)
        self.assertIn("SYDNEY", compute_session(early, self.config).active_sessions)

    def test_no_active_session_yields_empty_tuple_and_no_window_position(self):
        config = ScannerConfig(session_windows=(SessionWindow("TEST", 1, 0, 2, 0),))
        session_time = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        state = compute_session(session_time, config)
        self.assertEqual(state.active_sessions, ())
        self.assertIsNone(state.window_position)

    def test_window_position_is_a_fraction_between_zero_and_one(self):
        config = ScannerConfig(session_windows=(SessionWindow("TEST", 10, 0, 12, 0),))
        session_time = datetime(2026, 7, 4, 11, 0, 0, tzinfo=timezone.utc)
        state = compute_session(session_time, config)
        self.assertAlmostEqual(state.window_position, 0.5, places=6)

    def test_naive_timestamp_fails_closed_to_empty_session_state(self):
        session_time = datetime(2026, 7, 4, 10, 0, 0)  # no tzinfo
        state = compute_session(session_time, self.config)
        self.assertEqual(state.active_sessions, ())
        self.assertIsNone(state.window_position)


if __name__ == "__main__":
    unittest.main()
