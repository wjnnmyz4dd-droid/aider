"""WeeklyInstitutionalReviewGenerator tests — composes an already-built
PeriodReport (never recomputes it) into a narrative report with
recurring-mistake detection (ADR-021 item 7)."""

from __future__ import annotations

import unittest

from phantom_pipeline.research_desk.config import ResearchDeskConfig
from phantom_pipeline.research_desk.institutional_review import WeeklyInstitutionalReviewGenerator

from tests.phantom_pipeline.research_desk._fixtures import NOW, make_period_report


class TestGenerate(unittest.TestCase):
    def test_report_carries_period_reports_own_best_worst_values(self):
        period_report = make_period_report(worst_pair="XAUUSD")
        report = WeeklyInstitutionalReviewGenerator().generate("r1", period_report, NOW)

        self.assertEqual(report.worst_pair, "XAUUSD")
        self.assertEqual(report.best_pair, period_report.best_pair)

    def test_performance_review_reflects_forward_test_report(self):
        period_report = make_period_report()
        report = WeeklyInstitutionalReviewGenerator().generate("r1", period_report, NOW)
        self.assertIn("0.6", report.performance_review)

    def test_recurring_mistakes_detected_above_threshold(self):
        period_report = make_period_report(compliance_blocks={"NEWS_BLACKOUT": 5})
        generator = WeeklyInstitutionalReviewGenerator(ResearchDeskConfig(recurring_mistake_min_occurrences=2))
        report = generator.generate("r1", period_report, NOW)

        self.assertEqual(len(report.recurring_mistakes), 1)
        self.assertIn("NEWS_BLACKOUT", report.recurring_mistakes[0].description)

    def test_below_threshold_check_not_flagged(self):
        period_report = make_period_report(compliance_blocks={"RARE_CHECK": 1})
        generator = WeeklyInstitutionalReviewGenerator(ResearchDeskConfig(recurring_mistake_min_occurrences=2))
        report = generator.generate("r1", period_report, NOW)
        self.assertEqual(report.recurring_mistakes, ())

    def test_no_market_research_report_states_so_honestly(self):
        period_report = make_period_report()
        report = WeeklyInstitutionalReviewGenerator().generate("r1", period_report, NOW)
        self.assertIn("No market research report supplied", report.market_review)

    def test_research_recommendations_passed_through_verbatim(self):
        from phantom_pipeline.knowledge import ResearchSuggestion
        from phantom_pipeline.knowledge.models import ResearchCategory

        suggestion = ResearchSuggestion(
            schema_version=1, category=ResearchCategory.SESSION, description="test suggestion",
            supporting_evidence=(), generated_at=NOW,
        )
        period_report = make_period_report()
        report = WeeklyInstitutionalReviewGenerator().generate(
            "r1", period_report, NOW, research_recommendations=(suggestion,)
        )
        self.assertEqual(report.research_recommendations, (suggestion,))
        self.assertIn("test suggestion", report.improvement_opportunities)


if __name__ == "__main__":
    unittest.main()
