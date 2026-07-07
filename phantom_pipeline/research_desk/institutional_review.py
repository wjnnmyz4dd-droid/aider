"""Weekly Institutional Review (`ADR-021` §3, item 7).

Composes an already-built `paper_trading.PeriodReport` (never recomputes
any of its statistics) plus an optional `MarketResearchReport` and
already-generated `knowledge.ResearchSuggestion`s into one narrative
report. Recurring mistakes are read directly from `PeriodReport`'s own
already-attributed `compliance_blocks_by_check`/`execution_blocks_by_check`
dictionaries — never a third counting pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from ..knowledge import ResearchSuggestion
from ..paper_trading import PeriodReport
from .config import DEFAULT_CONFIG, ResearchDeskConfig
from .models import InstitutionalReviewReport, MarketResearchReport, RecurringMistake, SCHEMA_VERSION


class WeeklyInstitutionalReviewGenerator:
    def __init__(self, config: ResearchDeskConfig = DEFAULT_CONFIG) -> None:
        self._config = config

    def _recurring_mistakes(self, period_report: PeriodReport) -> Tuple[RecurringMistake, ...]:
        mistakes = []
        for check, count in period_report.compliance_blocks_by_check.items():
            if count >= self._config.recurring_mistake_min_occurrences:
                mistakes.append(
                    RecurringMistake(
                        description=f"Compliance check {check!r} blocked trades {count} time(s) this period.",
                        occurrence_count=count,
                        example_trace_ids=(),
                    )
                )
        for check, count in period_report.execution_blocks_by_check.items():
            if count >= self._config.recurring_mistake_min_occurrences:
                mistakes.append(
                    RecurringMistake(
                        description=f"Execution check {check!r} blocked trades {count} time(s) this period.",
                        occurrence_count=count,
                        example_trace_ids=(),
                    )
                )
        return tuple(mistakes)

    def generate(
        self,
        report_id: str,
        period_report: PeriodReport,
        now: datetime,
        market_research_report: Optional[MarketResearchReport] = None,
        research_recommendations: Tuple[ResearchSuggestion, ...] = (),
    ) -> InstitutionalReviewReport:
        ftr = period_report.forward_test_report

        executive_summary = (
            f"{period_report.period_kind} review: {ftr.trade_count} trade(s), "
            f"win rate {ftr.win_rate}, expectancy {ftr.expectancy}."
        )
        performance_review = (
            f"Win rate {ftr.win_rate}, profit factor {ftr.profit_factor}, "
            f"expectancy {ftr.expectancy}, max drawdown {ftr.max_drawdown}."
        )
        risk_review = f"Daily drawdown {ftr.daily_drawdown_pct}%, total drawdown {ftr.total_drawdown_pct}%."
        # ADR-022 Amendment 1 §A1.2 item 5 — reads the already-built
        # statistical_risk_trend/backtest `period_report` itself already
        # carries (paper_trading.PeriodReport, ADR-022 Amendment 1 §A1.2
        # item 3); never computes a new statistical value.
        if period_report.statistical_risk_trend is not None and period_report.statistical_risk_trend.points:
            latest = period_report.statistical_risk_trend.points[-1]
            risk_review += (
                f" Latest statistical risk: {latest.statistical_recommendation.value} "
                f"(risk of ruin {latest.risk_of_ruin}, portfolio heat {latest.portfolio_heat})."
            )
        if period_report.statistical_risk_backtest is not None and period_report.statistical_risk_backtest.sample_size > 0:
            backtest = period_report.statistical_risk_backtest
            risk_review += (
                f" Following every statistical recommendation this period would have changed PnL by "
                f"{backtest.improvement:.2f} (actual {backtest.actual_total_pnl:.2f} vs. "
                f"hypothetical {backtest.hypothetical_total_pnl:.2f})."
            )
        compliance_review = (
            f"Kill switch active: {period_report.kill_switch_active}. "
            f"Daily lockout active: {period_report.daily_lockout_active}. "
            f"Decisions by verdict: {period_report.compliance_decisions_by_verdict}."
        )
        execution_review = (
            f"Average validation latency {ftr.average_validation_latency_seconds}s, "
            f"average fill latency {ftr.average_fill_latency_seconds}s, "
            f"duplicate prevention count {ftr.duplicate_prevention_count}."
        )
        market_review = (
            market_research_report.macro_news_summary if market_research_report is not None
            else "No market research report supplied for this period."
        )

        return InstitutionalReviewReport(
            schema_version=SCHEMA_VERSION,
            report_id=report_id,
            period_kind=period_report.period_kind,
            window_start=period_report.window_start,
            window_end=period_report.window_end,
            generated_at=now,
            executive_summary=executive_summary,
            performance_review=performance_review,
            risk_review=risk_review,
            compliance_review=compliance_review,
            execution_review=execution_review,
            market_review=market_review,
            best_pair=period_report.best_pair,
            worst_pair=period_report.worst_pair,
            best_session=period_report.best_session,
            worst_session=period_report.worst_session,
            best_regime=period_report.best_regime,
            worst_regime=period_report.worst_regime,
            recurring_mistakes=self._recurring_mistakes(period_report),
            improvement_opportunities=tuple(s.description for s in research_recommendations),
            research_recommendations=research_recommendations,
        )


__all__ = ["WeeklyInstitutionalReviewGenerator"]
