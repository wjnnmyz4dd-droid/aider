"""End-to-end Research Desk integration tests: trade thesis + journal +
market research + institutional review all indexed into the *same*
KnowledgeEngine (never a second RAG system), replay determinism, and a
bounded performance check (ADR-021)."""

from __future__ import annotations

import time
import unittest

from phantom_pipeline.knowledge import DocumentKind, KnowledgeDocument
from phantom_pipeline.knowledge.engine import KnowledgeEngine
from phantom_pipeline.research_desk.debate import BullBearDebateAgent
from phantom_pipeline.research_desk.institutional_review import WeeklyInstitutionalReviewGenerator
from phantom_pipeline.research_desk.market_research import MarketResearchAgent
from phantom_pipeline.research_desk.trade_journal import AITradeJournal
from phantom_pipeline.research_desk.trade_thesis import TradeThesisGenerator

from tests.phantom_pipeline.research_desk._fixtures import (
    NOW,
    make_news_calendar_state,
    make_period_report,
    make_scanner_observation,
    make_trade_provenance_record,
)


class TestSharedKnowledgeEngineReuse(unittest.TestCase):
    """ADR-021 Hard Rule 3: every new artifact indexes into the SAME
    KnowledgeEngine already built for ADR-020 -- never a second store."""

    def test_trade_thesis_and_journal_entry_are_both_searchable_via_one_engine(self):
        engine = KnowledgeEngine()
        record = make_trade_provenance_record("t1", executed=True, realized_pnl=75.0)

        thesis = TradeThesisGenerator().generate(record, NOW)
        entry = AITradeJournal().create_entry(record, NOW)

        thesis_doc = KnowledgeDocument(
            schema_version=1, document_id=f"thesis-{thesis.trace_id}", kind=DocumentKind.TRADE_JOURNAL,
            title=f"Trade thesis {thesis.trace_id}", content=thesis.institutional_context + " " + thesis.expected_continuation,
            source_path=None, content_hash="h1", metadata={"trace_id": thesis.trace_id}, ingested_at=NOW,
        )
        entry_doc = KnowledgeDocument(
            schema_version=1, document_id=f"journal-{entry.trace_id}", kind=DocumentKind.TRADE_JOURNAL,
            title=f"Journal entry {entry.trace_id}", content=entry.entry_reason,
            source_path=None, content_hash="h2", metadata={"trace_id": entry.trace_id}, ingested_at=NOW,
        )
        engine.ingest_document(thesis_doc)
        engine.ingest_document(entry_doc)

        self.assertEqual(engine.metrics.documents_indexed_count, 2)
        results = engine.search("session breakout", top_k=5)
        self.assertGreater(len(results), 0)

    def test_institutional_review_recommendations_reuse_knowledge_research_suggestion_type(self):
        from phantom_pipeline.knowledge import ResearchSuggestion

        engine = KnowledgeEngine()
        period_report = make_period_report()
        suggestions = engine.suggest_research(period_report, NOW)

        review = WeeklyInstitutionalReviewGenerator().generate(
            "r1", period_report, NOW, research_recommendations=suggestions
        )
        for recommendation in review.research_recommendations:
            self.assertIsInstance(recommendation, ResearchSuggestion)


class TestReplayDeterminism(unittest.TestCase):
    def test_independent_generators_produce_identical_thesis_and_journal(self):
        record_a = make_trade_provenance_record("t1", executed=True)
        record_b = make_trade_provenance_record("t1", executed=True)

        thesis_a = TradeThesisGenerator().generate(record_a, NOW)
        thesis_b = TradeThesisGenerator().generate(record_b, NOW)
        self.assertEqual(thesis_a, thesis_b)

        entry_a = AITradeJournal().create_entry(record_a, NOW)
        entry_b = AITradeJournal().create_entry(record_b, NOW)
        self.assertEqual(entry_a, entry_b)

    def test_independent_debate_agents_produce_identical_thesis(self):
        obs = make_scanner_observation()
        thesis_a = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)
        thesis_b = BullBearDebateAgent().generate_thesis("r1", "EURUSD", obs, NOW)
        self.assertEqual(thesis_a, thesis_b)


class TestBoundedPerformance(unittest.TestCase):
    def test_generating_100_trade_theses_and_journal_entries_completes_quickly(self):
        thesis_generator = TradeThesisGenerator()
        journal = AITradeJournal()
        start = time.monotonic()
        for i in range(100):
            record = make_trade_provenance_record(f"perf-{i}", executed=(i % 2 == 0), realized_pnl=float(i))
            thesis_generator.generate(record, NOW)
            journal.create_entry(record, NOW)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 10.0, "generating 100 theses+journal entries should stay well under 10s")


class TestMarketResearchAndDebateTogether(unittest.TestCase):
    def test_full_market_research_and_debate_cycle(self):
        observations = [("EURUSD", make_scanner_observation()), ("GBPUSD", make_scanner_observation())]
        market_report = MarketResearchAgent().generate_daily("r1", NOW, observations, make_news_calendar_state())
        debate_agent = BullBearDebateAgent()
        theses = [debate_agent.generate_thesis("r1", symbol, obs, NOW) for symbol, obs in observations]

        self.assertEqual(len(market_report.findings), 2)
        self.assertEqual(len(theses), 2)
        for thesis in theses:
            self.assertIn("not a trading signal", thesis.final_summary)


if __name__ == "__main__":
    unittest.main()
