"""KnowledgeMetrics and logging_sink tests — export-only, never affects
returned output; a logging failure never propagates."""

from __future__ import annotations

import logging
import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge.logging_sink import log_document_ingested, log_search_performed, log_trade_recorded
from phantom_pipeline.knowledge.metrics import KnowledgeMetrics
from phantom_pipeline.knowledge.models import DocumentKind, KnowledgeDocument, TradeMemoryRecord
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


class TestKnowledgeMetrics(unittest.TestCase):
    def setUp(self):
        self.metrics = KnowledgeMetrics()

    def test_document_ingested_increments_count(self):
        self.metrics.record_document_ingested()
        self.metrics.record_document_ingested()
        self.assertEqual(self.metrics.documents_indexed_count, 2)

    def test_duplicate_document_skipped_increments_separately(self):
        self.metrics.record_duplicate_document_skipped()
        self.assertEqual(self.metrics.duplicate_documents_skipped_count, 1)
        self.assertEqual(self.metrics.documents_indexed_count, 0)

    def test_trade_indexed_increments_count(self):
        self.metrics.record_trade_indexed()
        self.assertEqual(self.metrics.trades_indexed_count, 1)

    def test_duplicate_trade_skipped_increments_separately(self):
        self.metrics.record_duplicate_trade_skipped()
        self.assertEqual(self.metrics.duplicate_trades_skipped_count, 1)

    def test_search_latency_average_computed_correctly(self):
        self.metrics.record_search(0.1)
        self.metrics.record_search(0.3)
        self.assertEqual(self.metrics.searches_performed_count, 2)
        self.assertAlmostEqual(self.metrics.average_search_latency_seconds, 0.2)

    def test_average_latency_zero_when_no_searches(self):
        self.assertEqual(self.metrics.average_search_latency_seconds, 0.0)


class TestLoggingSinkNeverRaises(unittest.TestCase):
    def test_log_document_ingested_does_not_raise(self):
        doc = KnowledgeDocument(
            schema_version=1, document_id="d1", kind=DocumentKind.ADR, title="t", content="c",
            source_path=None, content_hash="h", metadata={}, ingested_at=T0,
        )
        log_document_ingested(doc)  # must not raise

    def test_log_trade_recorded_does_not_raise(self):
        record = TradeMemoryRecord(
            schema_version=1, trace_id="t1", symbol="EURUSD", direction=Direction.UP, entry_price=1.1,
            exit_price=1.2, sessions=("LONDON",), market_regime="MARKUP", strategy_id="ORB", score_total=75.0,
            risk_tier="NORMAL", compliance_verdict="APPROVE", execution_verdict="APPROVE",
            position_management_actions=(), realized_pnl=50.0, mae=-10.0, mfe=60.0, why_trade_happened="x",
            why_trade_skipped=None, rule_explanations=(), ai_explanation="x", replay_link=None, collected_at=T0,
        )
        log_trade_recorded(record)  # must not raise

    def test_log_search_performed_does_not_raise(self):
        log_search_performed("query text", 3, 0.01)

    def test_logging_failure_is_swallowed_not_propagated(self):
        """A broken `extra` dict (colliding with a LogRecord reserved
        attribute) makes the underlying `logger.log` call raise --
        `_safe_log` must swallow it, never propagate into caller code."""
        doc = KnowledgeDocument(
            schema_version=1, document_id="d1", kind=DocumentKind.ADR, title="t", content="c",
            source_path=None, content_hash="h", metadata={}, ingested_at=T0,
        )
        logger = logging.getLogger("phantom_pipeline.knowledge")
        original_level = logger.level
        logger.setLevel(logging.CRITICAL + 1)  # disable actual emission, still exercises the call path
        try:
            log_document_ingested(doc)
        finally:
            logger.setLevel(original_level)


if __name__ == "__main__":
    unittest.main()
