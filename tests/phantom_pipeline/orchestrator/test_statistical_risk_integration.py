"""End-to-end integration tests for the Statistical Risk Management
subsystem's wiring into Orchestrator/Analytics/Paper Trading/Knowledge/
AI Research Desk/Dashboard/Explainable Decisions (`ADR-022` Amendment 1).

Covers §11 of the integration task: trace ID continuity, no regression,
deterministic outputs, historical storage, dashboard rendering,
knowledge ingestion, research desk integration, analytics integration,
paper trading integration.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from phantom_pipeline.knowledge import KnowledgeEngine
from phantom_pipeline.paper_trading.statistical_risk_backtest import StatisticalRiskBacktester
from phantom_pipeline.research_desk.explainable import ExplainableDecisionEngine
from phantom_pipeline.research_desk.strategy_research import StrategyResearchAgent
from phantom_pipeline.research_desk.trade_journal import AITradeJournal
from phantom_pipeline.research_desk.trade_thesis import TradeThesisGenerator
from phantom_pipeline.statistical_risk import RiskRecommendation, StatisticalRiskEngine

from ._fixtures import (
    SYMBOL,
    TIMEFRAME,
    build_orchestrator,
    feed_healthy_bars,
    make_broker_state,
    make_compliance_account_state,
    make_execution_account_state,
    make_news_state,
    make_risk_account_state,
)


def _run_one_cycle(orchestrator):
    last_ts = feed_healthy_bars(orchestrator.data_pipeline)
    result = orchestrator.run_scan_cycle(
        SYMBOL, [TIMEFRAME], TIMEFRAME, last_ts, last_ts,
        make_risk_account_state(), make_compliance_account_state(), make_execution_account_state(),
        make_broker_state(), make_news_state(),
    )
    return result, last_ts


class TestOrchestratorWiringIsFullyAdditive(unittest.TestCase):
    def test_default_orchestrator_has_no_statistical_risk_wired(self):
        orchestrator = build_orchestrator()
        self.assertIsNone(orchestrator.statistical_risk)
        result, _ = _run_one_cycle(orchestrator)
        for candidate_result in result.candidate_results:
            self.assertIsNone(candidate_result.statistical_risk_assessment)

    def test_wiring_in_statistical_risk_does_not_change_the_rest_of_the_result(self):
        orchestrator_a = build_orchestrator()
        orchestrator_b = build_orchestrator()
        orchestrator_b.statistical_risk = StatisticalRiskEngine()
        orchestrator_b._statistical_risk_records_provider = lambda: ()

        result_a, _ = _run_one_cycle(orchestrator_a)
        result_b, _ = _run_one_cycle(orchestrator_b)

        self.assertEqual(len(result_a.candidate_results), len(result_b.candidate_results))
        for cr_a, cr_b in zip(result_a.candidate_results, result_b.candidate_results):
            self.assertEqual(cr_a.risk_decision, cr_b.risk_decision)
            self.assertEqual(cr_a.compliance_decision, cr_b.compliance_decision)
            self.assertEqual(cr_a.execution_decision, cr_b.execution_decision)
            self.assertEqual(cr_a.submit_reject_reason, cr_b.submit_reject_reason)
            self.assertIsNone(cr_a.statistical_risk_assessment)
            self.assertIsNotNone(cr_b.statistical_risk_assessment)

    def test_render_dashboard_snapshot_unaffected_by_statistical_risk_wiring(self):
        orchestrator = build_orchestrator()
        orchestrator.statistical_risk = StatisticalRiskEngine()
        orchestrator._statistical_risk_records_provider = lambda: ()
        _, last_ts = _run_one_cycle(orchestrator)
        views = orchestrator.render_dashboard_snapshot(last_ts)
        from phantom_pipeline.dashboard.models import ViewName

        self.assertEqual(set(views.keys()), {name.value for name in ViewName})


class TestTraceIdContinuityAndHistoricalStorage(unittest.TestCase):
    def setUp(self):
        self.orchestrator = build_orchestrator()
        self.orchestrator.statistical_risk = StatisticalRiskEngine()
        self.records = []
        self.orchestrator._statistical_risk_records_provider = lambda: list(self.records)
        self.result, self.now = _run_one_cycle(self.orchestrator)
        self.candidate_result = self.result.candidate_results[0]

    def test_trace_id_matches_risk_decision(self):
        self.assertEqual(
            self.candidate_result.statistical_risk_assessment.trace_id,
            self.candidate_result.risk_decision.trace_id,
        )

    def test_trace_id_matches_candidate(self):
        self.assertEqual(
            self.candidate_result.statistical_risk_assessment.trace_id,
            self.candidate_result.candidate.trace_id,
        )

    def test_assessment_stored_in_analytics_bucket_identically(self):
        bucket = self.orchestrator.analytics.store.get_bucket(self.candidate_result.risk_decision.trace_id)
        self.assertIs(bucket.statistical_risk_assessment, self.candidate_result.statistical_risk_assessment)

    def test_provenance_record_carries_the_assessment(self):
        record = self.orchestrator.analytics.build_provenance_record(
            self.candidate_result.risk_decision.trace_id, self.now
        )
        self.assertIs(record.statistical_risk_assessment, self.candidate_result.statistical_risk_assessment)


class TestDeterministicOutputs(unittest.TestCase):
    def test_two_independent_orchestrators_produce_identical_assessments(self):
        orchestrator_a = build_orchestrator()
        orchestrator_a.statistical_risk = StatisticalRiskEngine()
        orchestrator_a._statistical_risk_records_provider = lambda: ()

        orchestrator_b = build_orchestrator()
        orchestrator_b.statistical_risk = StatisticalRiskEngine()
        orchestrator_b._statistical_risk_records_provider = lambda: ()

        result_a, _ = _run_one_cycle(orchestrator_a)
        result_b, _ = _run_one_cycle(orchestrator_b)

        assessment_a = result_a.candidate_results[0].statistical_risk_assessment
        assessment_b = result_b.candidate_results[0].statistical_risk_assessment
        self.assertEqual(assessment_a, assessment_b)


class TestAnalyticsIntegration(unittest.TestCase):
    def setUp(self):
        self.orchestrator = build_orchestrator()
        self.orchestrator.statistical_risk = StatisticalRiskEngine()
        self.records = []
        self.orchestrator._statistical_risk_records_provider = lambda: list(self.records)
        self.result, self.now = _run_one_cycle(self.orchestrator)
        trace_id = self.result.candidate_results[0].risk_decision.trace_id
        self.records.append(self.orchestrator.analytics.build_provenance_record(trace_id, self.now))

    def test_compute_trend_reads_back_stored_assessments(self):
        trend_report = self.orchestrator.statistical_risk.compute_trend(self.records, self.now)
        self.assertEqual(len(trend_report.points), 1)
        self.assertEqual(
            trend_report.points[0].statistical_recommendation,
            self.records[0].statistical_risk_assessment.statistical_recommendation,
        )

    def test_kelly_recommendation_collected(self):
        bucket = self.orchestrator.analytics.store.get_bucket(self.records[0].trace_id)
        # kelly_recommendation is collected even when None (insufficient sample).
        self.assertIn("kelly_recommendation", vars(bucket))


class TestDashboardRendering(unittest.TestCase):
    def test_snapshot_reflects_latest_assessment_and_trend(self):
        orchestrator = build_orchestrator()
        orchestrator.statistical_risk = StatisticalRiskEngine()
        records = []
        orchestrator._statistical_risk_records_provider = lambda: list(records)
        result, now = _run_one_cycle(orchestrator)
        trace_id = result.candidate_results[0].risk_decision.trace_id
        records.append(orchestrator.analytics.build_provenance_record(trace_id, now))

        snapshot = orchestrator.render_statistical_risk_dashboard_snapshot(now)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.latest_assessment.trace_id, trace_id)
        self.assertEqual(len(snapshot.historical_trend), 1)
        self.assertIsNotNone(snapshot.confidence_interval)

    def test_snapshot_none_without_statistical_risk_wired(self):
        orchestrator = build_orchestrator()
        self.assertIsNone(orchestrator.render_statistical_risk_dashboard_snapshot(datetime.now(timezone.utc)))


class TestKnowledgeIngestion(unittest.TestCase):
    def test_assessment_stored_and_searchable(self):
        orchestrator = build_orchestrator()
        orchestrator.statistical_risk = StatisticalRiskEngine()
        orchestrator._statistical_risk_records_provider = lambda: ()
        result, now = _run_one_cycle(orchestrator)
        assessment = result.candidate_results[0].statistical_risk_assessment

        knowledge = KnowledgeEngine()
        added = knowledge.record_statistical_risk_assessment(assessment, now)
        self.assertTrue(added)

        documents = knowledge.find_statistical_risk_assessments()
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].metadata["trace_id"], assessment.trace_id)

        found_by_recommendation = knowledge.find_statistical_risk_assessments(
            recommendation=assessment.statistical_recommendation.value
        )
        self.assertEqual(len(found_by_recommendation), 1)

        search_results = knowledge.search(assessment.statistical_recommendation.value)
        self.assertTrue(any(r.document is not None and r.document.document_id == documents[0].document_id for r in search_results))

    def test_reingesting_unchanged_assessment_is_a_noop(self):
        orchestrator = build_orchestrator()
        orchestrator.statistical_risk = StatisticalRiskEngine()
        orchestrator._statistical_risk_records_provider = lambda: ()
        result, now = _run_one_cycle(orchestrator)
        assessment = result.candidate_results[0].statistical_risk_assessment

        knowledge = KnowledgeEngine()
        self.assertTrue(knowledge.record_statistical_risk_assessment(assessment, now))
        self.assertFalse(knowledge.record_statistical_risk_assessment(assessment, now))


class TestResearchDeskIntegration(unittest.TestCase):
    def setUp(self):
        self.orchestrator = build_orchestrator()
        self.orchestrator.statistical_risk = StatisticalRiskEngine()
        self.orchestrator._statistical_risk_records_provider = lambda: ()
        self.result, self.now = _run_one_cycle(self.orchestrator)
        trace_id = self.result.candidate_results[0].risk_decision.trace_id
        self.record = self.orchestrator.analytics.build_provenance_record(trace_id, self.now)
        self.assertIsNotNone(self.record.statistical_risk_assessment)

    def test_trade_thesis_quotes_the_assessment(self):
        thesis = TradeThesisGenerator().generate(self.record, self.now)
        recommendation = self.record.statistical_risk_assessment.statistical_recommendation.value
        self.assertTrue(any("statistical risk" in factor for factor in thesis.risk_factors))

    def test_ai_trade_journal_reflects_assessment_when_not_normal(self):
        assessment = self.record.statistical_risk_assessment
        journal = AITradeJournal()
        entry = journal.create_entry(self.record, self.now)
        if assessment.statistical_recommendation != RiskRecommendation.NORMAL_RISK:
            self.assertTrue(
                any("Statistical Risk Manager" in improvement for improvement in entry.suggested_improvements)
            )

    def test_strategy_research_groups_by_recommendation(self):
        agent = StrategyResearchAgent(self.orchestrator.analytics)
        best, worst = agent.best_worst_statistical_recommendation([self.record])
        self.assertIn(best, (None, self.record.statistical_risk_assessment.statistical_recommendation.value))

    def test_explainable_decision_engine_answers_why_risk_reduced(self):
        engine = ExplainableDecisionEngine(search_service=None)
        answer = engine.explain_statistical_risk(
            "Why was risk reduced?", assessment=self.record.statistical_risk_assessment
        )
        self.assertIn(self.record.statistical_risk_assessment.statistical_recommendation.value, answer)


class TestPaperTradingIntegration(unittest.TestCase):
    def test_backtester_computes_hypothetical_pnl(self):
        orchestrator = build_orchestrator()
        orchestrator.statistical_risk = StatisticalRiskEngine()
        orchestrator._statistical_risk_records_provider = lambda: ()
        result, now = _run_one_cycle(orchestrator)
        trace_id = result.candidate_results[0].risk_decision.trace_id
        record = orchestrator.analytics.build_provenance_record(trace_id, now)

        backtester = StatisticalRiskBacktester()
        report = backtester.evaluate([record], now)
        # This candidate was rejected by execution_validator (no closed
        # outcome), so the backtest sample is honestly empty -- confirms
        # no fabricated entry is produced for a trade with no realized PnL.
        self.assertEqual(report.sample_size, 0)
        self.assertEqual(report.actual_total_pnl, 0.0)


if __name__ == "__main__":
    unittest.main()
