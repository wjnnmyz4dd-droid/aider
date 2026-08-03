"""Market Research Agent (`ADR-021` §3, item 1) — analyzes market
structure, volatility, liquidity, sessions, and (within the real data
Phantom has) macro news / the economic calendar, from already-produced
`ScannerObservation`s and `NewsCalendarState`. Produces daily/weekly
reports. Never re-derives a fact `Scanner`/`Compliance Engine` already
computed — every summary is built from an already-recorded field.

**Macro news / economic calendar, stated honestly** (`ADR-021` Hard Rule
5): Phantom has no rich macro-news feed. The only real, live input is
`compliance_engine.models.NewsCalendarState.blackout_windows` — a narrow
blackout-window list `ADR-006` §8 already defines for compliance
purposes. Both `analyze_macro_news` and `analyze_economic_calendar` read
that same feed (there is no second, richer source to read from) and say
so in their own output rather than fabricating additional detail.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional, Sequence, Tuple

from ..compliance_engine.models import NewsCalendarState
from ..scanner.models import MarketPhase, ScannerObservation
from ..statistical_risk.models import StatisticalRiskAssessment
from .models import MarketResearchReport, MarketStructureFinding, SCHEMA_VERSION


class MarketResearchAgent:
    def analyze_structure(self, observation: ScannerObservation) -> str:
        if not observation.structure:
            return "No structural signals recorded."
        kinds = sorted({signal.kind.value for signal in observation.structure})
        return f"Structural signals present: {', '.join(kinds)}."

    def analyze_volatility(self, observation: ScannerObservation) -> str:
        label = observation.volatility.label.value
        ratio = observation.volatility.ratio
        if ratio is None:
            return f"Volatility: {label} (no numeric reading available)."
        return f"Volatility: {label} ({ratio:.5f})."

    def analyze_liquidity(self, observation: ScannerObservation) -> str:
        if not observation.liquidity_events:
            return "No liquidity events recorded."
        kinds = sorted({event.kind for event in observation.liquidity_events})
        return f"Liquidity events: {', '.join(kinds)}."

    def analyze_sessions(self, observation: ScannerObservation) -> Tuple[str, ...]:
        return observation.session.active_sessions

    def analyze_regime(self, observation: ScannerObservation) -> Optional[str]:
        if observation.phase in (MarketPhase.UNKNOWN, MarketPhase.UNDEFINED):
            return None
        return observation.phase.value

    def analyze_macro_news(self, news_state: Optional[NewsCalendarState]) -> str:
        if news_state is None:
            return "No news calendar data supplied for this period."
        if news_state.feed_stale:
            return "News calendar feed is stale — treated as unavailable per ADR-006 SS8, never assumed clear."
        if not news_state.blackout_windows:
            return "No active news blackout windows; no rich macro-news feed exists beyond this blackout-window calendar."
        currencies = sorted({w.currency for w in news_state.blackout_windows})
        return f"Active news blackout windows for: {', '.join(currencies)}."

    def analyze_economic_calendar(self, news_state: Optional[NewsCalendarState]) -> str:
        """Reads the same `NewsCalendarState` as `analyze_macro_news` —
        Phantom has no separate, richer economic-calendar feed."""
        if news_state is None:
            return "No economic calendar data supplied for this period."
        if news_state.feed_stale:
            return "Economic calendar feed is stale — treated as unavailable per ADR-006 SS8."
        return f"{len(news_state.blackout_windows)} blackout window(s) on the calendar this period."

    def analyze_statistical_risk(self, assessment: Optional[StatisticalRiskAssessment]) -> Optional[str]:
        """Quotes the already-produced `StatisticalRiskAssessment` verbatim
        (`ADR-022` Amendment 1 §A1.2 item 5) — `None` when none was
        supplied for this symbol; never computes a new statistical value."""
        if assessment is None:
            return None
        return (
            f"Statistical risk: {assessment.statistical_recommendation.value} "
            f"(confidence {assessment.confidence_score}, portfolio heat {assessment.portfolio_heat})."
        )

    def build_finding(
        self,
        symbol: str,
        observation: ScannerObservation,
        statistical_risk_assessment: Optional[StatisticalRiskAssessment] = None,
    ) -> MarketStructureFinding:
        return MarketStructureFinding(
            symbol=symbol,
            structure_summary=self.analyze_structure(observation),
            volatility_summary=self.analyze_volatility(observation),
            liquidity_summary=self.analyze_liquidity(observation),
            active_sessions=self.analyze_sessions(observation),
            regime=self.analyze_regime(observation),
            statistical_risk_summary=self.analyze_statistical_risk(statistical_risk_assessment),
        )

    def generate_report(
        self,
        report_id: str,
        period_kind: str,
        window_start: datetime,
        window_end: datetime,
        now: datetime,
        observations: Sequence[Tuple[str, ScannerObservation]],
        news_state: Optional[NewsCalendarState] = None,
        statistical_risk_assessments: Optional[Dict[str, StatisticalRiskAssessment]] = None,
    ) -> MarketResearchReport:
        statistical_risk_assessments = statistical_risk_assessments or {}
        findings = tuple(
            self.build_finding(symbol, observation, statistical_risk_assessments.get(symbol))
            for symbol, observation in observations
        )
        active_currencies = ()
        if news_state is not None and not news_state.feed_stale:
            active_currencies = tuple(sorted({w.currency for w in news_state.blackout_windows}))
        return MarketResearchReport(
            schema_version=SCHEMA_VERSION,
            report_id=report_id,
            period_kind=period_kind,
            window_start=window_start,
            window_end=window_end,
            generated_at=now,
            findings=findings,
            macro_news_summary=self.analyze_macro_news(news_state),
            economic_calendar_summary=self.analyze_economic_calendar(news_state),
            active_blackout_currencies=active_currencies,
        )

    def generate_daily(
        self, report_id: str, now: datetime, observations: Sequence[Tuple[str, ScannerObservation]],
        news_state: Optional[NewsCalendarState] = None,
        statistical_risk_assessments: Optional[Dict[str, StatisticalRiskAssessment]] = None,
    ) -> MarketResearchReport:
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.generate_report(
            report_id, "DAILY", window_start, now, now, observations, news_state, statistical_risk_assessments
        )

    def generate_weekly(
        self, report_id: str, now: datetime, observations: Sequence[Tuple[str, ScannerObservation]],
        news_state: Optional[NewsCalendarState] = None,
        statistical_risk_assessments: Optional[Dict[str, StatisticalRiskAssessment]] = None,
    ) -> MarketResearchReport:
        window_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.generate_report(
            report_id, "WEEKLY", window_start, now, now, observations, news_state, statistical_risk_assessments
        )


__all__ = ["MarketResearchAgent"]
