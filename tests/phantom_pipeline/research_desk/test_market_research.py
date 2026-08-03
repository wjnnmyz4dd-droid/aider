"""MarketResearchAgent tests — structure/volatility/liquidity/session/
regime analysis and daily/weekly report generation (ADR-021 item 1)."""

from __future__ import annotations

import unittest

from phantom_pipeline.research_desk.market_research import MarketResearchAgent
from phantom_pipeline.scanner.models import MarketPhase

from tests.phantom_pipeline.research_desk._fixtures import NOW, make_news_calendar_state, make_scanner_observation


class TestAnalyzeStructure(unittest.TestCase):
    def test_empty_structure_reported_honestly(self):
        obs = make_scanner_observation()
        summary = MarketResearchAgent().analyze_structure(obs)
        self.assertIn("No structural signals", summary)


class TestAnalyzeVolatility(unittest.TestCase):
    def test_includes_label_and_value(self):
        obs = make_scanner_observation()
        summary = MarketResearchAgent().analyze_volatility(obs)
        self.assertIn("NORMAL", summary)


class TestAnalyzeLiquidity(unittest.TestCase):
    def test_empty_liquidity_reported_honestly(self):
        obs = make_scanner_observation()
        summary = MarketResearchAgent().analyze_liquidity(obs)
        self.assertIn("No liquidity events", summary)


class TestAnalyzeSessions(unittest.TestCase):
    def test_returns_active_sessions(self):
        obs = make_scanner_observation(sessions=("LONDON", "NEW_YORK"))
        sessions = MarketResearchAgent().analyze_sessions(obs)
        self.assertEqual(sessions, ("LONDON", "NEW_YORK"))


class TestAnalyzeRegime(unittest.TestCase):
    def test_markup_phase_returned(self):
        obs = make_scanner_observation(phase=MarketPhase.MARKUP)
        self.assertEqual(MarketResearchAgent().analyze_regime(obs), "MARKUP")

    def test_unknown_phase_returns_none(self):
        obs = make_scanner_observation(phase=MarketPhase.UNKNOWN)
        self.assertIsNone(MarketResearchAgent().analyze_regime(obs))


class TestAnalyzeMacroNewsAndCalendar(unittest.TestCase):
    def test_none_state_reported_honestly(self):
        agent = MarketResearchAgent()
        self.assertIn("No news calendar data", agent.analyze_macro_news(None))
        self.assertIn("No economic calendar data", agent.analyze_economic_calendar(None))

    def test_stale_feed_fails_closed(self):
        state = make_news_calendar_state(stale=True)
        agent = MarketResearchAgent()
        self.assertIn("stale", agent.analyze_macro_news(state))
        self.assertIn("stale", agent.analyze_economic_calendar(state))

    def test_active_blackout_windows_reported(self):
        state = make_news_calendar_state(currencies=("USD", "EUR"))
        summary = MarketResearchAgent().analyze_macro_news(state)
        self.assertIn("USD", summary)
        self.assertIn("EUR", summary)

    def test_no_windows_states_no_rich_feed_exists(self):
        state = make_news_calendar_state(currencies=())
        summary = MarketResearchAgent().analyze_macro_news(state)
        self.assertIn("no rich macro-news feed", summary)


class TestGenerateReport(unittest.TestCase):
    def test_daily_report_contains_one_finding_per_symbol(self):
        agent = MarketResearchAgent()
        observations = [("EURUSD", make_scanner_observation()), ("GBPUSD", make_scanner_observation())]
        report = agent.generate_daily("report-1", NOW, observations, make_news_calendar_state())

        self.assertEqual(report.period_kind, "DAILY")
        self.assertEqual(len(report.findings), 2)
        self.assertEqual({f.symbol for f in report.findings}, {"EURUSD", "GBPUSD"})

    def test_weekly_report_period_kind(self):
        agent = MarketResearchAgent()
        report = agent.generate_weekly("report-2", NOW, [], None)
        self.assertEqual(report.period_kind, "WEEKLY")

    def test_report_is_deterministic(self):
        agent = MarketResearchAgent()
        observations = [("EURUSD", make_scanner_observation())]
        report_a = agent.generate_daily("r", NOW, observations, make_news_calendar_state())
        report_b = agent.generate_daily("r", NOW, observations, make_news_calendar_state())
        self.assertEqual(report_a, report_b)

    def test_empty_observations_yields_empty_findings(self):
        agent = MarketResearchAgent()
        report = agent.generate_daily("r", NOW, [], None)
        self.assertEqual(report.findings, ())

    def test_stale_news_state_yields_no_active_blackout_currencies(self):
        agent = MarketResearchAgent()
        report = agent.generate_daily("r", NOW, [], make_news_calendar_state(stale=True))
        self.assertEqual(report.active_blackout_currencies, ())


if __name__ == "__main__":
    unittest.main()
