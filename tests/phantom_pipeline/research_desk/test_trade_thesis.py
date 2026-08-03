"""TradeThesisGenerator tests — every field read from the same already-
produced TradeProvenanceRecord (ADR-021 item 3, Hard Rule 8)."""

from __future__ import annotations

import unittest

from phantom_pipeline.position_manager.models import ManagementAction
from phantom_pipeline.research_desk.trade_thesis import TradeThesisGenerator

from tests.phantom_pipeline.research_desk._fixtures import NOW, make_position_management_decision, make_trade_provenance_record


class TestExecutedTradeThesis(unittest.TestCase):
    def setUp(self):
        self.record = make_trade_provenance_record(
            "t1", executed=True, realized_pnl=50.0,
            position_management_decisions=(make_position_management_decision("t1", ManagementAction.MOVE_TO_BREAKEVEN),),
        )
        self.thesis = TradeThesisGenerator().generate(self.record, NOW)

    def test_trace_id_propagated(self):
        self.assertEqual(self.thesis.trace_id, "t1")

    def test_why_setup_existed_reads_candidate_fields(self):
        self.assertIn("session breakout", self.thesis.why_setup_existed)

    def test_why_it_qualified_reads_score_result(self):
        self.assertIn("75.00", self.thesis.why_it_qualified)

    def test_why_it_succeeded_reflects_positive_pnl(self):
        self.assertIn("succeeded", self.thesis.why_it_failed_or_succeeded)
        self.assertIn("50.00", self.thesis.why_it_failed_or_succeeded)

    def test_institutional_context_reads_scanner_observation(self):
        self.assertIn("MARKUP", self.thesis.institutional_context)

    def test_expected_continuation_reflects_bullish_phase(self):
        self.assertIn("upward", self.thesis.expected_continuation)

    def test_risk_factors_empty_when_no_binding_constraints_or_blocks(self):
        self.assertEqual(self.thesis.risk_factors, ())


class TestRejectedTradeThesis(unittest.TestCase):
    def test_why_it_failed_reflects_rejection(self):
        record = make_trade_provenance_record("t2", executed=False)
        thesis = TradeThesisGenerator().generate(record, NOW)
        self.assertIn("Rejected at ComplianceEngine", thesis.why_it_failed_or_succeeded)

    def test_risk_factors_include_compliance_block(self):
        record = make_trade_provenance_record("t2", executed=False)
        thesis = TradeThesisGenerator().generate(record, NOW)
        self.assertTrue(any("compliance concern" in f for f in thesis.risk_factors))


class TestLessonsLearned(unittest.TestCase):
    def test_rejected_trade_notes_rejection_is_not_a_loss(self):
        record = make_trade_provenance_record("t2", executed=False)
        thesis = TradeThesisGenerator().generate(record, NOW)
        self.assertTrue(any("not a loss" in lesson for lesson in thesis.lessons_learned))

    def test_losing_closed_trade_suggests_reviewing_entry_criteria(self):
        record = make_trade_provenance_record("t3", executed=True, realized_pnl=-25.0)
        thesis = TradeThesisGenerator().generate(record, NOW)
        self.assertTrue(any("closed at a loss" in lesson for lesson in thesis.lessons_learned))


class TestMissingData(unittest.TestCase):
    def test_missing_scanner_observation_handled_honestly(self):
        record = make_trade_provenance_record("t4", executed=True, include_scanner_observation=False)
        thesis = TradeThesisGenerator().generate(record, NOW)
        self.assertIn("cannot be derived", thesis.institutional_context)
        self.assertIn("cannot be derived", thesis.expected_continuation)


class TestDeterminism(unittest.TestCase):
    def test_identical_record_yields_identical_thesis(self):
        record_a = make_trade_provenance_record("t1", executed=True)
        record_b = make_trade_provenance_record("t1", executed=True)
        thesis_a = TradeThesisGenerator().generate(record_a, NOW)
        thesis_b = TradeThesisGenerator().generate(record_b, NOW)
        self.assertEqual(thesis_a, thesis_b)


if __name__ == "__main__":
    unittest.main()
