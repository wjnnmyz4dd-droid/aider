"""KnowledgeEngine / ExplanationEngine tests — deterministic explanation
templates, replay determinism, ingestion + search integration, weekly
review / research suggestions, and the dashboard snapshot (ADR-020)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge.engine import ExplanationEngine, KnowledgeEngine
from phantom_pipeline.knowledge.models import ResearchCategory
from phantom_pipeline.paper_trading.forward_test_engine import ForwardTestReport
from phantom_pipeline.paper_trading.report_generator import PeriodReport
from phantom_pipeline.position_manager.models import ManagementAction
from phantom_pipeline.risk_engine.models import RiskTier

from tests.phantom_pipeline.knowledge._fixtures import T0, make_position_management_decision, make_trade_provenance_record

NOW = T0


def _forward_test_report() -> ForwardTestReport:
    return ForwardTestReport(
        schema_version=1, generated_at=NOW, window_start=NOW, window_end=NOW, trade_count=10,
        win_rate=0.6, profit_factor=1.5, expectancy=10.0, average_rr=1.8, max_drawdown=5.0,
        daily_drawdown_pct=1.0, total_drawdown_pct=2.0, average_validation_latency_seconds=0.01,
        average_broker_latency_seconds=0.02, average_fill_latency_seconds=0.03, average_slippage=0.0001,
        slippage_sample_size=10, missed_trade_count=1, blocked_trade_count=2, duplicate_prevention_count=0,
        recovery_attempt_count=0, recovery_success_rate=1.0, average_recovery_time_seconds=0.0,
        analytics_version="1.0.0-phase1",
    )


def _period_report(worst_pair="GBPUSD", worst_session="TOKYO", worst_regime="MARKDOWN", top_check_count=5) -> PeriodReport:
    return PeriodReport(
        schema_version=1, period_kind="WEEKLY", window_start=NOW, window_end=NOW, generated_at=NOW,
        forward_test_report=_forward_test_report(), prop_firm_status=None,
        best_pair="EURUSD", worst_pair=worst_pair, best_session="LONDON", worst_session=worst_session,
        best_regime="MARKUP", worst_regime=worst_regime,
        biggest_winner_trace_id="t1", biggest_winner_pnl=100.0, biggest_loser_trace_id="t2", biggest_loser_pnl=-50.0,
        compliance_blocks_by_check={"NEWS_BLACKOUT": top_check_count, "SPREAD_LIMIT": 1},
        execution_blocks_by_check={}, compliance_decisions_by_verdict={"APPROVE": 8, "BLOCK": 2},
        kill_switch_active=False, daily_lockout_active=False,
    )


class TestExplanationEngineRiskDecision(unittest.TestCase):
    def setUp(self):
        self.engine = ExplanationEngine()

    def test_normal_tier_explains_approval(self):
        record = make_trade_provenance_record("t1", executed=True)
        explanation = self.engine.explain_risk_decision(record.risk_decision)
        self.assertIn("Risk approved", explanation)
        self.assertIn("NORMAL", explanation)

    def test_halted_tier_explains_zero_risk(self):
        record = make_trade_provenance_record("t2", executed=False)
        explanation = self.engine.explain_risk_decision(record.risk_decision)
        self.assertIn("HALTED", explanation)
        self.assertIn("reduced to zero", explanation)

    def test_none_risk_decision_handled_without_raising(self):
        explanation = self.engine.explain_risk_decision(None)
        self.assertIn("No risk decision", explanation)


class TestExplanationEngineComplianceDecision(unittest.TestCase):
    def test_block_explains_blocking_rules(self):
        record = make_trade_provenance_record("t1", executed=False)
        explanation = ExplanationEngine().explain_compliance_decision(record.compliance_decision)
        self.assertIn("blocked", explanation)
        self.assertIn("NEWS_BLACKOUT", explanation)

    def test_approve_explains_reason_codes(self):
        record = make_trade_provenance_record("t1", executed=True)
        explanation = ExplanationEngine().explain_compliance_decision(record.compliance_decision)
        self.assertIn("approved", explanation)


class TestExplanationEngineExecutionDecision(unittest.TestCase):
    def test_reject_explains_blocking_reasons(self):
        record = make_trade_provenance_record("t1", executed=False)
        explanation = ExplanationEngine().explain_execution_decision(record.execution_decision)
        self.assertIn("failed", explanation)

    def test_approve_explains_reason_codes(self):
        record = make_trade_provenance_record("t1", executed=True)
        explanation = ExplanationEngine().explain_execution_decision(record.execution_decision)
        self.assertIn("approved", explanation)


class TestExplanationEnginePositionManagement(unittest.TestCase):
    def test_no_action_produces_no_explanation(self):
        decision = make_position_management_decision("t1", ManagementAction.NO_ACTION)
        explanations = ExplanationEngine().explain_position_management((decision,))
        self.assertEqual(explanations, ())

    def test_trailing_stop_moved_explanation(self):
        decision = make_position_management_decision("t1", ManagementAction.TRAIL_STOP)
        explanations = ExplanationEngine().explain_position_management((decision,))
        self.assertEqual(len(explanations), 1)
        self.assertIn("Trailing stop moved", explanations[0])

    def test_emergency_close_explanation(self):
        decision = make_position_management_decision("t1", ManagementAction.EMERGENCY_CLOSE)
        explanations = ExplanationEngine().explain_position_management((decision,))
        self.assertIn("emergency-closed", explanations[0])


class TestExplainTradeExecutedVsRejected(unittest.TestCase):
    def test_executed_trade_has_why_happened_and_no_why_skipped(self):
        record = make_trade_provenance_record("t1", executed=True)
        why_happened, why_skipped, rule_explanations, ai_explanation = ExplanationEngine().explain_trade(record)
        self.assertTrue(why_happened)
        self.assertIsNone(why_skipped)
        self.assertTrue(rule_explanations)
        self.assertEqual(ai_explanation, why_happened)

    def test_rejected_trade_has_why_skipped_and_empty_why_happened(self):
        record = make_trade_provenance_record("t2", executed=False)
        why_happened, why_skipped, rule_explanations, ai_explanation = ExplanationEngine().explain_trade(record)
        self.assertEqual(why_happened, "")
        self.assertTrue(why_skipped)
        self.assertIn("Rejected at ComplianceEngine", why_skipped)
        self.assertEqual(ai_explanation, why_skipped)


class TestExplainTradeDeterminism(unittest.TestCase):
    def test_identical_record_yields_identical_explanation(self):
        record_a = make_trade_provenance_record("t1", executed=True)
        record_b = make_trade_provenance_record("t1", executed=True)
        result_a = ExplanationEngine().explain_trade(record_a)
        result_b = ExplanationEngine().explain_trade(record_b)
        self.assertEqual(result_a, result_b)


class TestKnowledgeEngineIngestDocument(unittest.TestCase):
    def test_ingest_new_document_increments_metrics(self):
        from phantom_pipeline.knowledge.models import DocumentKind, KnowledgeDocument

        engine = KnowledgeEngine()
        doc = KnowledgeDocument(
            schema_version=1, document_id="d1", kind=DocumentKind.ADR, title="t", content="risk engine content",
            source_path=None, content_hash="h1", metadata={}, ingested_at=NOW,
        )
        added = engine.ingest_document(doc)
        self.assertTrue(added)
        self.assertEqual(engine.metrics.documents_indexed_count, 1)
        self.assertEqual(engine.metrics.duplicate_documents_skipped_count, 0)

    def test_duplicate_document_increments_duplicate_metric(self):
        from phantom_pipeline.knowledge.models import DocumentKind, KnowledgeDocument

        engine = KnowledgeEngine()
        doc = KnowledgeDocument(
            schema_version=1, document_id="d1", kind=DocumentKind.ADR, title="t", content="same content",
            source_path=None, content_hash="h1", metadata={}, ingested_at=NOW,
        )
        engine.ingest_document(doc)
        added_again = engine.ingest_document(doc)
        self.assertFalse(added_again)
        self.assertEqual(engine.metrics.duplicate_documents_skipped_count, 1)


class TestKnowledgeEngineRecordTrade(unittest.TestCase):
    def test_record_trade_builds_and_stores_memory_record(self):
        engine = KnowledgeEngine()
        record = make_trade_provenance_record("t1", executed=True)

        memory = engine.record_trade(record, NOW)

        self.assertEqual(memory.trace_id, "t1")
        self.assertEqual(engine.trade_memory.get("t1"), memory)
        self.assertEqual(engine.metrics.trades_indexed_count, 1)

    def test_duplicate_trade_increments_duplicate_metric(self):
        engine = KnowledgeEngine()
        record = make_trade_provenance_record("t1", executed=True)
        engine.record_trade(record, NOW)
        engine.record_trade(record, NOW)
        self.assertEqual(engine.metrics.duplicate_trades_skipped_count, 1)

    def test_recorded_trade_is_findable_via_search(self):
        engine = KnowledgeEngine()
        record = make_trade_provenance_record("t1", executed=True)
        memory = engine.record_trade(record, NOW)

        results = engine.search(memory.why_trade_happened, top_k=1)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].trade.trace_id, "t1")
        self.assertEqual(engine.metrics.searches_performed_count, 1)


class TestKnowledgeEngineResearchAndWeeklyReview(unittest.TestCase):
    def test_suggest_research_flags_worst_session_pair_regime_and_top_block(self):
        engine = KnowledgeEngine()
        report = _period_report()

        suggestions = engine.suggest_research(report, NOW)

        categories = {s.category for s in suggestions}
        self.assertIn(ResearchCategory.SESSION, categories)
        self.assertIn(ResearchCategory.FILTER, categories)
        self.assertIn(ResearchCategory.MARKET_OBSERVATION, categories)
        self.assertIn(ResearchCategory.RISK, categories)

    def test_suggestions_reference_the_reports_own_worst_values_never_invented(self):
        engine = KnowledgeEngine()
        report = _period_report(worst_pair="XAUUSD")
        suggestions = engine.suggest_research(report, NOW)
        pair_suggestion = next(s for s in suggestions if s.category == ResearchCategory.FILTER)
        self.assertIn("XAUUSD", pair_suggestion.description)

    def test_generate_weekly_review_returns_report_verbatim_and_suggestions(self):
        engine = KnowledgeEngine()
        report = _period_report()

        returned_report, suggestions = engine.generate_weekly_review(report, NOW)

        self.assertIs(returned_report, report)
        self.assertTrue(suggestions)

    def test_research_suggestions_accumulate_in_dashboard_queue(self):
        engine = KnowledgeEngine()
        engine.suggest_research(_period_report(), NOW)
        snapshot = engine.render_dashboard_snapshot(NOW)
        self.assertTrue(snapshot.research_queue)


class TestKnowledgeEngineDashboardSnapshot(unittest.TestCase):
    def test_snapshot_reflects_recorded_trades(self):
        engine = KnowledgeEngine()
        engine.record_trade(make_trade_provenance_record("t1", executed=True), NOW)
        engine.record_trade(make_trade_provenance_record("t2", executed=False), NOW)

        snapshot = engine.render_dashboard_snapshot(NOW)

        self.assertEqual(len(snapshot.recent_trade_memory), 2)
        self.assertEqual(len(snapshot.recent_ai_explanations), 2)
        self.assertEqual(len(snapshot.recent_insights), 2)

    def test_empty_engine_produces_empty_snapshot(self):
        engine = KnowledgeEngine()
        snapshot = engine.render_dashboard_snapshot(NOW)
        self.assertEqual(snapshot.recent_trade_memory, ())
        self.assertEqual(snapshot.research_queue, ())


if __name__ == "__main__":
    unittest.main()
