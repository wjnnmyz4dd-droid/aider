"""Structural tests for research_desk/models.py — immutability, tuple
coercion, and boundary guarantees (ADR-021 Hard Rules)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.knowledge.engine import KnowledgeEngine
from phantom_pipeline.research_desk.models import (
    ComparisonReport,
    DebateStance,
    DebateThesis,
    InstitutionalReviewReport,
    JournalEntry,
    MarketResearchReport,
    MarketStructureFinding,
    RecurringMistake,
    ResearchDeskDashboardSnapshot,
    RuleCombinationFinding,
    ThesisCase,
    TradeThesis,
)

from tests.phantom_pipeline.research_desk._fixtures import NOW


class TestMarketResearchReport(unittest.TestCase):
    def test_tuples_coerced(self):
        finding = MarketStructureFinding(
            symbol="EURUSD", structure_summary="s", volatility_summary="v", liquidity_summary="l",
            active_sessions=["LONDON"], regime="MARKUP",
        )
        self.assertEqual(finding.active_sessions, ("LONDON",))

        report = MarketResearchReport(
            schema_version=1, report_id="r1", period_kind="DAILY", window_start=NOW, window_end=NOW,
            generated_at=NOW, findings=[finding], macro_news_summary="m", economic_calendar_summary="e",
            active_blackout_currencies=["USD"],
        )
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.active_blackout_currencies, ("USD",))

    def test_is_frozen(self):
        report = MarketResearchReport(
            schema_version=1, report_id="r1", period_kind="DAILY", window_start=NOW, window_end=NOW,
            generated_at=NOW, findings=(), macro_news_summary="m", economic_calendar_summary="e",
            active_blackout_currencies=(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.macro_news_summary = "x"  # type: ignore[misc]


class TestDebateThesis(unittest.TestCase):
    def test_case_evidence_coerced_to_tuple(self):
        case = ThesisCase(stance=DebateStance.BULLISH, summary="s", supporting_evidence=["a", "b"])
        self.assertEqual(case.supporting_evidence, ("a", "b"))

    def test_no_signal_shaped_fields_on_thesis_or_case(self):
        forbidden = ("direction", "lot_size", "entry_price", "stop_loss", "take_profit")
        for f in dataclasses.fields(DebateThesis):
            self.assertNotIn(f.name, forbidden)
        for f in dataclasses.fields(ThesisCase):
            self.assertNotIn(f.name, forbidden)


class TestJournalEntry(unittest.TestCase):
    def test_is_frozen(self):
        entry = JournalEntry(
            schema_version=1, trace_id="t1", entry_reason="e", risk_reason="r", compliance_decision="APPROVE",
            execution_quality="q", exit_reason=None, profit_or_loss=None, lessons_learned=(),
            suggested_improvements=(), created_at=NOW,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.entry_reason = "x"  # type: ignore[misc]


class TestRuleCombinationFinding(unittest.TestCase):
    def test_rule_codes_coerced_to_tuple(self):
        finding = RuleCombinationFinding(rule_codes=["A", "B"], occurrence_count=3, average_pnl=10.0, classification="STRONGEST")
        self.assertEqual(finding.rule_codes, ("A", "B"))


class TestRecurringMistake(unittest.TestCase):
    def test_example_trace_ids_coerced(self):
        mistake = RecurringMistake(description="d", occurrence_count=2, example_trace_ids=["t1", "t2"])
        self.assertEqual(mistake.example_trace_ids, ("t1", "t2"))


class TestComparisonReport(unittest.TestCase):
    def test_metric_deltas_coerced_to_dict(self):
        report = ComparisonReport(
            report_id="r1", generated_at=NOW, period_a_label="a", period_b_label="b",
            metric_deltas=[("win_rate", 0.1)], narrative="n",
        )
        self.assertEqual(report.metric_deltas, {"win_rate": 0.1})


class TestResearchDeskDashboardSnapshot(unittest.TestCase):
    def test_tuples_coerced(self):
        knowledge_snapshot = KnowledgeEngine().render_dashboard_snapshot(NOW)
        snapshot = ResearchDeskDashboardSnapshot(
            schema_version=1, generated_at=NOW, knowledge_snapshot=knowledge_snapshot,
            research_summaries=["a"], learning_trends=["b"], strategy_evolution=["c"], optimization_history=["d"],
        )
        self.assertEqual(snapshot.research_summaries, ("a",))
        self.assertEqual(snapshot.learning_trends, ("b",))
        self.assertEqual(snapshot.strategy_evolution, ("c",))
        self.assertEqual(snapshot.optimization_history, ("d",))


if __name__ == "__main__":
    unittest.main()
