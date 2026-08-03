"""Ingestion tests — markdown/document ingestion, content-hash
deduplication and incremental re-ingestion, and `TradeProvenanceRecord`
-> `TradeMemoryRecord` field mapping (ADR-020 Hard Rule 8: every field
read, never re-derived)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge.ingestion import (
    KnowledgeDocumentStore,
    build_trade_memory_record,
    ingest_directory,
    ingest_markdown_file,
    ingest_repository_documents,
)
from phantom_pipeline.knowledge.models import DocumentKind
from phantom_pipeline.position_manager.models import ManagementAction
from phantom_pipeline.scanner.models import Direction, MarketPhase

from tests.phantom_pipeline.knowledge._fixtures import make_position_management_decision, make_trade_provenance_record

T0 = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


class TestIngestMarkdownFile(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def test_reads_content_and_extracts_title_from_heading(self):
        path = os.path.join(self.tmp_dir, "doc.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# My Title\n\nSome content here.\n")

        document = ingest_markdown_file(path, DocumentKind.ADR, T0)

        self.assertEqual(document.title, "My Title")
        self.assertIn("Some content here.", document.content)
        self.assertEqual(document.kind, DocumentKind.ADR)
        self.assertEqual(document.source_path, path)

    def test_falls_back_to_filename_when_no_heading(self):
        path = os.path.join(self.tmp_dir, "no_heading.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("just text, no heading\n")

        document = ingest_markdown_file(path, DocumentKind.PLAN_DOC, T0)

        self.assertEqual(document.title, "no_heading.md")

    def test_content_hash_is_deterministic(self):
        path = os.path.join(self.tmp_dir, "doc.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("stable content")

        doc1 = ingest_markdown_file(path, DocumentKind.ADR, T0)
        doc2 = ingest_markdown_file(path, DocumentKind.ADR, T0)

        self.assertEqual(doc1.content_hash, doc2.content_hash)


class TestIngestDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def test_ingests_every_markdown_file_in_directory(self):
        for name in ("a.md", "b.md"):
            with open(os.path.join(self.tmp_dir, name), "w", encoding="utf-8") as handle:
                handle.write(f"# {name}\ncontent")
        with open(os.path.join(self.tmp_dir, "ignored.txt"), "w", encoding="utf-8") as handle:
            handle.write("not markdown")

        documents = ingest_directory(self.tmp_dir, DocumentKind.ADR, T0)

        self.assertEqual(len(documents), 2)

    def test_missing_directory_returns_empty_tuple(self):
        documents = ingest_directory(os.path.join(self.tmp_dir, "does-not-exist"), DocumentKind.ADR, T0)
        self.assertEqual(documents, ())


class TestIngestRepositoryDocuments(unittest.TestCase):
    def test_ingests_known_root_docs_and_adr_and_plans_directories(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        documents = ingest_repository_documents(repo_root, T0)

        kinds = {d.kind for d in documents}
        self.assertIn(DocumentKind.ADR, kinds)
        self.assertIn(DocumentKind.CHANGELOG, kinds)
        self.assertGreater(len(documents), 5)

    def test_missing_repo_root_yields_no_crash_and_empty_result(self):
        documents = ingest_repository_documents("/definitely/does/not/exist", T0)
        self.assertEqual(documents, ())


class TestKnowledgeDocumentStoreDeduplication(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)
        self.path = os.path.join(self.tmp_dir, "doc.md")

    def test_re_ingesting_unchanged_file_is_a_no_op(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("original content")
        store = KnowledgeDocumentStore()

        first = store.add(ingest_markdown_file(self.path, DocumentKind.ADR, T0))
        second = store.add(ingest_markdown_file(self.path, DocumentKind.ADR, T0))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(store.count, 1)

    def test_re_ingesting_changed_file_updates_the_stored_document(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("version one")
        store = KnowledgeDocumentStore()
        store.add(ingest_markdown_file(self.path, DocumentKind.ADR, T0))

        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("version two")
        updated = store.add(ingest_markdown_file(self.path, DocumentKind.ADR, T0))

        self.assertTrue(updated)
        self.assertEqual(store.count, 1)
        self.assertIn("version two", store.get(self.path).content)

    def test_get_and_all(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("content")
        store = KnowledgeDocumentStore()
        doc = ingest_markdown_file(self.path, DocumentKind.ADR, T0)
        store.add(doc)

        self.assertEqual(store.get(self.path).content_hash, doc.content_hash)
        self.assertEqual(len(store.all()), 1)


class TestBuildTradeMemoryRecordExecuted(unittest.TestCase):
    def setUp(self):
        self.record = make_trade_provenance_record(
            "trace-1", executed=True, realized_pnl=42.0,
            position_management_decisions=(make_position_management_decision("trace-1", ManagementAction.MOVE_TO_BREAKEVEN),),
        )

    def test_symbol_and_direction_read_from_candidate(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.symbol, "EURUSD")
        self.assertEqual(memory.direction, Direction.UP)

    def test_session_and_regime_read_from_scanner_observation(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.sessions, ("LONDON",))
        self.assertEqual(memory.market_regime, MarketPhase.MARKUP.value)

    def test_verdicts_read_from_decisions(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.compliance_verdict, "APPROVE")
        self.assertEqual(memory.execution_verdict, "APPROVE")
        self.assertEqual(memory.risk_tier, "NORMAL")

    def test_pnl_mae_mfe_read_from_final_outcome(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.realized_pnl, 42.0)
        self.assertEqual(memory.mae, -10.0)
        self.assertEqual(memory.mfe, 60.0)

    def test_entry_price_read_from_first_fill_report(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.entry_price, 1.1000)

    def test_exit_price_read_from_latest_closed_position_update(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.exit_price, 1.1050)

    def test_position_management_actions_read_from_decisions(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.position_management_actions, ("MOVE_TO_BREAKEVEN",))

    def test_replay_link_passed_through_verbatim(self):
        memory = build_trade_memory_record(self.record, "happened", None, (), "ai", "http://replay/trace-1", T0)
        self.assertEqual(memory.replay_link, "http://replay/trace-1")


class TestBuildTradeMemoryRecordRejected(unittest.TestCase):
    def test_rejected_trade_has_no_entry_or_exit_price(self):
        record = make_trade_provenance_record("trace-2", executed=False)
        memory = build_trade_memory_record(record, "", "skipped because news blackout", (), "skipped because news blackout", None, T0)
        self.assertIsNone(memory.entry_price)
        self.assertIsNone(memory.exit_price)
        self.assertIsNone(memory.realized_pnl)
        self.assertEqual(memory.why_trade_skipped, "skipped because news blackout")

    def test_missing_scanner_observation_yields_empty_sessions_and_none_regime(self):
        record = make_trade_provenance_record("trace-3", include_scanner_observation=False)
        memory = build_trade_memory_record(record, "happened", None, (), "ai", None, T0)
        self.assertEqual(memory.sessions, ())
        self.assertIsNone(memory.market_regime)


if __name__ == "__main__":
    unittest.main()
