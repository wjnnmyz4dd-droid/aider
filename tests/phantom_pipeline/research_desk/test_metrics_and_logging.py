"""ResearchDeskMetrics and logging_sink tests — export-only, never
affects returned output; a logging failure never propagates."""

from __future__ import annotations

import unittest

from phantom_pipeline.research_desk.logging_sink import (
    log_debate_thesis_generated,
    log_journal_entry_created,
    log_market_report_generated,
    log_question_asked,
)
from phantom_pipeline.research_desk.metrics import ResearchDeskMetrics


class TestResearchDeskMetrics(unittest.TestCase):
    def setUp(self):
        self.metrics = ResearchDeskMetrics()

    def test_market_report_generated_increments(self):
        self.metrics.record_market_report_generated()
        self.assertEqual(self.metrics.market_reports_generated_count, 1)

    def test_debate_thesis_generated_increments(self):
        self.metrics.record_debate_thesis_generated()
        self.assertEqual(self.metrics.debate_theses_generated_count, 1)

    def test_trade_thesis_generated_increments(self):
        self.metrics.record_trade_thesis_generated()
        self.assertEqual(self.metrics.trade_theses_generated_count, 1)

    def test_journal_entry_created_increments(self):
        self.metrics.record_journal_entry_created()
        self.assertEqual(self.metrics.journal_entries_created_count, 1)

    def test_institutional_review_generated_increments(self):
        self.metrics.record_institutional_review_generated()
        self.assertEqual(self.metrics.institutional_reviews_generated_count, 1)

    def test_question_latency_average(self):
        self.metrics.record_question_asked(0.1)
        self.metrics.record_question_asked(0.3)
        self.assertEqual(self.metrics.questions_asked_count, 2)
        self.assertAlmostEqual(self.metrics.average_question_latency_seconds, 0.2)

    def test_average_latency_zero_when_no_questions(self):
        self.assertEqual(self.metrics.average_question_latency_seconds, 0.0)


class TestLoggingSinkNeverRaises(unittest.TestCase):
    def test_all_log_functions_do_not_raise(self):
        log_market_report_generated("r1", "DAILY")
        log_debate_thesis_generated("EURUSD", 0.5)
        log_journal_entry_created("t1")
        log_question_asked("why?", 3)


if __name__ == "__main__":
    unittest.main()
