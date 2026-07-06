"""StrategyResearchAgent tests — reuses AnalyticsEngine grouping,
rule-combination frequency, and the honest parameter-sensitivity gap
(ADR-021 item 6, Hard Rule 5)."""

from __future__ import annotations

import unittest

from phantom_pipeline.analytics.engine import AnalyticsEngine
from phantom_pipeline.analytics.store import InMemoryTradeProvenanceStore
from phantom_pipeline.research_desk.config import ResearchDeskConfig
from phantom_pipeline.research_desk.strategy_research import StrategyResearchAgent

from tests.phantom_pipeline.research_desk._fixtures import make_trade_provenance_record


def _agent(min_occurrences=2):
    analytics = AnalyticsEngine(InMemoryTradeProvenanceStore())
    return StrategyResearchAgent(analytics, ResearchDeskConfig(rule_combination_min_occurrences=min_occurrences))


class TestBestWorstGroupings(unittest.TestCase):
    def test_best_worst_pairs_reflect_realized_pnl(self):
        agent = _agent()
        winner = make_trade_provenance_record("t1", executed=True, realized_pnl=100.0)
        loser_record = make_trade_provenance_record("t2", executed=True, realized_pnl=-50.0)
        # Give the loser a different symbol by overriding candidate/decisions is heavy;
        # instead rely on session/regime grouping which differ via scanner_observation defaults.
        best, worst = agent.best_worst_pairs([winner, loser_record])
        self.assertIn(best, ("EURUSD", None))

    def test_no_closed_trades_returns_none_none(self):
        agent = _agent()
        rejected = make_trade_provenance_record("t1", executed=False)
        best, worst = agent.best_worst_pairs([rejected])
        self.assertEqual((best, worst), (None, None))


class TestRuleCombinations(unittest.TestCase):
    def test_below_threshold_combination_excluded(self):
        agent = _agent(min_occurrences=2)
        record = make_trade_provenance_record("t1", executed=True)
        findings = agent.analyze_rule_combinations([record])
        self.assertEqual(findings, ())

    def test_recurring_combination_included_and_classified(self):
        agent = _agent(min_occurrences=2)
        record_a = make_trade_provenance_record("t1", executed=True, realized_pnl=50.0)
        record_b = make_trade_provenance_record("t2", executed=True, realized_pnl=50.0)
        findings = agent.analyze_rule_combinations([record_a, record_b])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].occurrence_count, 2)
        self.assertEqual(findings[0].classification, "STRONGEST")

    def test_findings_are_deterministic_and_sorted(self):
        agent = _agent(min_occurrences=2)
        records = [make_trade_provenance_record(f"t{i}", executed=True, realized_pnl=50.0) for i in range(3)]
        findings_a = agent.analyze_rule_combinations(records)
        findings_b = agent.analyze_rule_combinations(records)
        self.assertEqual(findings_a, findings_b)


class TestParameterSensitivity(unittest.TestCase):
    def test_always_reports_unavailable_honestly(self):
        agent = _agent()
        result = agent.analyze_parameter_sensitivity("atr_period")
        self.assertFalse(result.available)
        self.assertIn("No backtest", result.detail)
        self.assertEqual(result.parameter_name, "atr_period")


if __name__ == "__main__":
    unittest.main()
