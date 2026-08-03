"""ResearchDeskDashboardBuilder tests — wraps knowledge.KnowledgeDashboardSnapshot
verbatim, never modifies dashboard/ or knowledge/ (ADR-021 item 9, Hard Rules 3-4)."""

from __future__ import annotations

import unittest

from phantom_pipeline.knowledge.engine import KnowledgeEngine
from phantom_pipeline.research_desk.config import ResearchDeskConfig
from phantom_pipeline.research_desk.dashboard import ResearchDeskDashboardBuilder

from tests.phantom_pipeline.research_desk._fixtures import NOW


class TestBuild(unittest.TestCase):
    def test_wraps_knowledge_snapshot_verbatim(self):
        knowledge_engine = KnowledgeEngine()
        knowledge_snapshot = knowledge_engine.render_dashboard_snapshot(NOW)

        snapshot = ResearchDeskDashboardBuilder().build(NOW, knowledge_snapshot)

        self.assertIs(snapshot.knowledge_snapshot, knowledge_snapshot)

    def test_research_summaries_truncated_to_configured_limit(self):
        knowledge_engine = KnowledgeEngine()
        knowledge_snapshot = knowledge_engine.render_dashboard_snapshot(NOW)
        builder = ResearchDeskDashboardBuilder(ResearchDeskConfig(recent_summaries_limit=2))

        snapshot = builder.build(NOW, knowledge_snapshot, research_summaries=["a", "b", "c", "d"])

        self.assertEqual(snapshot.research_summaries, ("c", "d"))

    def test_empty_inputs_produce_empty_tuples(self):
        knowledge_engine = KnowledgeEngine()
        knowledge_snapshot = knowledge_engine.render_dashboard_snapshot(NOW)
        snapshot = ResearchDeskDashboardBuilder().build(NOW, knowledge_snapshot)

        self.assertEqual(snapshot.learning_trends, ())
        self.assertEqual(snapshot.strategy_evolution, ())
        self.assertEqual(snapshot.optimization_history, ())


if __name__ == "__main__":
    unittest.main()
