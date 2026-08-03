"""Structural tests for knowledge/models.py — immutability, tuple/dict
coercion, and boundary guarantees (ADR-020 Hard Rules 1-3)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge.models import (
    DocumentKind,
    EmbeddingVector,
    KnowledgeDashboardSnapshot,
    KnowledgeDocument,
    ResearchCategory,
    ResearchSuggestion,
    SearchQuery,
    SearchResult,
    TradeMemoryRecord,
)
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def _document() -> KnowledgeDocument:
    return KnowledgeDocument(
        schema_version=1, document_id="doc-1", kind=DocumentKind.ADR, title="Test",
        content="hello world", source_path="/tmp/doc.md", content_hash="abc123",
        metadata={"a": "b"}, ingested_at=T0,
    )


def _trade_memory_record() -> TradeMemoryRecord:
    return TradeMemoryRecord(
        schema_version=1, trace_id="t1", symbol="EURUSD", direction=Direction.UP,
        entry_price=1.1, exit_price=1.2, sessions=("LONDON",), market_regime="MARKUP",
        strategy_id="ORB", score_total=75.0, risk_tier="NORMAL", compliance_verdict="APPROVE",
        execution_verdict="APPROVE", position_management_actions=("MOVE_TO_BREAKEVEN",),
        realized_pnl=50.0, mae=-10.0, mfe=60.0, why_trade_happened="because", why_trade_skipped=None,
        rule_explanations=("a", "b"), ai_explanation="because", replay_link=None, collected_at=T0,
    )


class TestKnowledgeDocument(unittest.TestCase):
    def test_metadata_coerced_to_dict(self):
        doc = KnowledgeDocument(
            schema_version=1, document_id="d", kind=DocumentKind.CHANGELOG, title="t", content="c",
            source_path=None, content_hash="h", metadata=(("a", "b"),), ingested_at=T0,
        )
        self.assertEqual(doc.metadata, {"a": "b"})

    def test_is_frozen(self):
        doc = _document()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            doc.title = "changed"  # type: ignore[misc]


class TestEmbeddingVector(unittest.TestCase):
    def test_vector_coerced_to_tuple(self):
        vector = EmbeddingVector(document_id="d", vector=[1.0, 2.0], model_name="m", dimension=2)
        self.assertEqual(vector.vector, (1.0, 2.0))


class TestSearchQuery(unittest.TestCase):
    def test_filters_default_to_empty_dict(self):
        query = SearchQuery(text="hello")
        self.assertEqual(query.filters, {})

    def test_filters_coerced_to_dict(self):
        query = SearchQuery(text="hello", filters={"kind": "ADR"})
        self.assertEqual(query.filters, {"kind": "ADR"})


class TestTradeMemoryRecord(unittest.TestCase):
    def test_tuples_coerced(self):
        record = TradeMemoryRecord(
            schema_version=1, trace_id="t1", symbol="EURUSD", direction=Direction.UP,
            entry_price=1.1, exit_price=1.2, sessions=["LONDON", "NEW_YORK"], market_regime="MARKUP",
            strategy_id="ORB", score_total=75.0, risk_tier="NORMAL", compliance_verdict="APPROVE",
            execution_verdict="APPROVE", position_management_actions=["MOVE_TO_BREAKEVEN"],
            realized_pnl=50.0, mae=-10.0, mfe=60.0, why_trade_happened="because", why_trade_skipped=None,
            rule_explanations=["a", "b"], ai_explanation="because", replay_link=None, collected_at=T0,
        )
        self.assertEqual(record.sessions, ("LONDON", "NEW_YORK"))
        self.assertEqual(record.position_management_actions, ("MOVE_TO_BREAKEVEN",))
        self.assertEqual(record.rule_explanations, ("a", "b"))

    def test_is_frozen(self):
        record = _trade_memory_record()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.realized_pnl = 999.0  # type: ignore[misc]

    def test_no_field_represents_a_trading_decision(self):
        """Boundary test (ADR-020 Hard Rule 2): no field name resembles a
        decision/execution/sizing authority this package must never hold."""
        forbidden = ("lot_size", "stop_loss", "take_profit", "submit", "approve_trade", "reject_trade")
        for f in dataclasses.fields(TradeMemoryRecord):
            for forbidden_fragment in forbidden:
                self.assertNotIn(forbidden_fragment, f.name.lower())


class TestResearchSuggestion(unittest.TestCase):
    def test_evidence_coerced_to_tuple(self):
        suggestion = ResearchSuggestion(
            schema_version=1, category=ResearchCategory.SESSION, description="d",
            supporting_evidence=["a", "b"], generated_at=T0,
        )
        self.assertEqual(suggestion.supporting_evidence, ("a", "b"))


class TestKnowledgeDashboardSnapshot(unittest.TestCase):
    def test_tuples_coerced(self):
        snapshot = KnowledgeDashboardSnapshot(
            schema_version=1, generated_at=T0, recent_insights=["a"], recent_trade_memory=[_trade_memory_record()],
            research_queue=[], recent_ai_explanations=["b"],
        )
        self.assertEqual(snapshot.recent_insights, ("a",))
        self.assertEqual(len(snapshot.recent_trade_memory), 1)
        self.assertEqual(snapshot.research_queue, ())
        self.assertEqual(snapshot.recent_ai_explanations, ("b",))


if __name__ == "__main__":
    unittest.main()
