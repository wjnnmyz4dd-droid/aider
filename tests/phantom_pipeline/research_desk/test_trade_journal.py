"""AITradeJournal tests — reuses knowledge.ExplanationEngine, adds
suggested_improvements; entries are read-only after creation
(ADR-021 item 5, Hard Rule 7)."""

from __future__ import annotations

import dataclasses
import unittest

from phantom_pipeline.research_desk.models import JournalEntry
from phantom_pipeline.research_desk.trade_journal import AITradeJournal

from tests.phantom_pipeline.research_desk._fixtures import NOW, make_trade_provenance_record


class TestCreateEntryExecuted(unittest.TestCase):
    def setUp(self):
        self.record = make_trade_provenance_record("t1", executed=True, realized_pnl=50.0)
        self.entry = AITradeJournal().create_entry(self.record, NOW)

    def test_trace_id_propagated(self):
        self.assertEqual(self.entry.trace_id, "t1")

    def test_entry_reason_populated(self):
        self.assertTrue(self.entry.entry_reason)

    def test_compliance_decision_is_verdict_string(self):
        self.assertEqual(self.entry.compliance_decision, "APPROVE")

    def test_exit_reason_and_pnl_read_from_final_outcome(self):
        self.assertEqual(self.entry.exit_reason, "TIME_EXIT")
        self.assertEqual(self.entry.profit_or_loss, 50.0)

    def test_no_suggested_improvements_for_clean_winning_trade(self):
        self.assertEqual(self.entry.suggested_improvements, ())


class TestCreateEntryRejected(unittest.TestCase):
    def test_compliance_block_produces_suggested_improvement(self):
        record = make_trade_provenance_record("t2", executed=False)
        entry = AITradeJournal().create_entry(record, NOW)

        self.assertEqual(entry.compliance_decision, "BLOCK")
        self.assertTrue(any("Compliance blocked" in s for s in entry.suggested_improvements))
        self.assertTrue(any("HALTED" in s for s in entry.suggested_improvements))


class TestCreateEntryLoss(unittest.TestCase):
    def test_losing_trade_suggests_reviewing_entry_criteria(self):
        record = make_trade_provenance_record("t3", executed=True, realized_pnl=-10.0)
        entry = AITradeJournal().create_entry(record, NOW)
        self.assertTrue(any("closed at a loss" in s for s in entry.suggested_improvements))


class TestReadOnlyAfterCreation(unittest.TestCase):
    def test_journal_entry_is_frozen(self):
        record = make_trade_provenance_record("t1", executed=True)
        entry = AITradeJournal().create_entry(record, NOW)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.profit_or_loss = 999.0  # type: ignore[misc]

    def test_no_update_method_exists_on_journal_entry_type(self):
        update_like = [name for name in dir(JournalEntry) if name.startswith(("set_", "update_", "edit_"))]
        self.assertEqual(update_like, [])

    def test_no_update_method_exists_on_ai_trade_journal(self):
        update_like = [name for name in dir(AITradeJournal) if name.startswith(("set_", "update_", "edit_"))]
        self.assertEqual(update_like, [])


class TestDeterminism(unittest.TestCase):
    def test_identical_record_yields_identical_entry(self):
        record_a = make_trade_provenance_record("t1", executed=True)
        record_b = make_trade_provenance_record("t1", executed=True)
        entry_a = AITradeJournal().create_entry(record_a, NOW)
        entry_b = AITradeJournal().create_entry(record_b, NOW)
        self.assertEqual(entry_a, entry_b)


if __name__ == "__main__":
    unittest.main()
