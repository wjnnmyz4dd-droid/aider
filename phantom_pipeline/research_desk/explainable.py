"""Explainable Decision Engine (`ADR-021` §3, item 8).

Every already-supported natural-language question shape ("why didn't
EURUSD trade today", "show every trade rejected by compliance", etc.)
is delegated to `knowledge.SemanticSearchService` — reused wholesale,
never duplicated (`ADR-021` §2). `compare_periods`/`what_changed_over`
are the genuinely new query shapes this module adds, built entirely
from two already-computed `paper_trading.PeriodReport`s' own fields —
never a third statistics implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Sequence, Tuple

from ..knowledge import SearchResult, SemanticSearchService
from ..paper_trading import PeriodReport
from ..statistical_risk.models import StatisticalRiskAssessment, StatisticalRiskTrendPoint
from .models import ComparisonReport

_COMPARABLE_METRICS = ("win_rate", "profit_factor", "expectancy", "max_drawdown", "trade_count")


def _metric_value(period_report: PeriodReport, name: str) -> "float | None":
    if name == "trade_count":
        return float(period_report.forward_test_report.trade_count)
    return getattr(period_report.forward_test_report, name)


class ExplainableDecisionEngine:
    def __init__(self, search_service: SemanticSearchService) -> None:
        self._search_service = search_service

    def ask(self, question: str, top_k: int = 10) -> Tuple[SearchResult, ...]:
        return self._search_service.search(question, top_k=top_k)

    def compare_periods(
        self,
        report_id: str,
        label_a: str,
        period_a: PeriodReport,
        label_b: str,
        period_b: PeriodReport,
        now: datetime,
    ) -> ComparisonReport:
        deltas = {}
        for name in _COMPARABLE_METRICS:
            value_a, value_b = _metric_value(period_a, name), _metric_value(period_b, name)
            if value_a is not None and value_b is not None:
                deltas[name] = value_b - value_a

        if deltas:
            narrative = f"{label_b} vs {label_a}: " + "; ".join(f"{name} changed by {delta:+.4f}" for name, delta in deltas.items())
        else:
            narrative = f"{label_b} vs {label_a}: no comparable metrics available."

        return ComparisonReport(
            report_id=report_id, generated_at=now, period_a_label=label_a, period_b_label=label_b,
            metric_deltas=deltas, narrative=narrative,
        )

    def what_changed_over(
        self,
        report_id: str,
        days: int,
        period_baseline: PeriodReport,
        period_recent: PeriodReport,
        now: datetime,
    ) -> ComparisonReport:
        comparison = self.compare_periods(
            report_id, f"{days}-days-ago baseline", period_baseline, "recent", period_recent, now
        )
        narrative = f"Over the last {days} days: {comparison.narrative}"
        return ComparisonReport(
            report_id=comparison.report_id, generated_at=now, period_a_label=comparison.period_a_label,
            period_b_label=comparison.period_b_label, metric_deltas=comparison.metric_deltas, narrative=narrative,
        )

    def explain_statistical_risk(
        self,
        question: str,
        assessment: Optional[StatisticalRiskAssessment] = None,
        history: Sequence[StatisticalRiskTrendPoint] = (),
        period_a: Optional[PeriodReport] = None,
        period_b: Optional[PeriodReport] = None,
        regime_assessments: Optional[Dict[str, StatisticalRiskAssessment]] = None,
    ) -> str:
        """Answers the 8 statistical-risk question shapes (`ADR-022`
        Amendment 1 §A1.2 item 7) via deterministic string templates built
        entirely from already-computed `StatisticalRiskAssessment`/
        `StatisticalRiskTrendPoint`/`PeriodReport` fields — no new
        statistical value is computed here, and a question this method
        cannot honestly answer from the supplied data says so rather than
        guessing."""
        lowered = question.lower()

        if ("compare" in lowered or "versus" in lowered or " vs " in lowered) and period_a is not None and period_b is not None:
            return self.compare_periods(
                "statistical-risk-comparison", "previous period", period_a, "current period", period_b,
                datetime.now(timezone.utc),
            ).narrative

        if "sharpe" in lowered and len(history) >= 2:
            first, last = history[0], history[-1]
            if first.sharpe_ratio is not None and last.sharpe_ratio is not None:
                delta = last.sharpe_ratio - first.sharpe_ratio
                return (
                    f"Sharpe ratio moved from {first.sharpe_ratio} to {last.sharpe_ratio} "
                    f"({delta:+.4f}) across the supplied history."
                )
            return "Sharpe ratio is not available for both ends of the supplied history."

        if "regime" in lowered and "lowest" in lowered:
            if not regime_assessments:
                return "No per-regime statistical risk assessments were supplied; cannot compare regimes."
            ranked = {
                regime: a.risk_of_ruin for regime, a in regime_assessments.items() if a.risk_of_ruin is not None
            }
            if not ranked:
                return "No regime has a computed risk of ruin in the supplied assessments."
            safest = min(ranked, key=lambda r: ranked[r])
            return f"{safest} has the lowest observed risk of ruin ({ranked[safest]}) among the supplied regimes."

        if "portfolio heat" in lowered or "elevated portfolio heat" in lowered:
            if assessment is None:
                return "No statistical risk assessment supplied; cannot explain portfolio heat."
            correlation = assessment.correlation_state
            return (
                f"Portfolio heat is {assessment.portfolio_heat}. Most concentrated correlation bucket: "
                f"{correlation.most_concentrated_bucket} ({correlation.max_bucket_concentration_count} position(s)). "
                f"Flagged buckets: {', '.join(correlation.flagged_buckets) or 'none'}."
            )

        if "risk of ruin" in lowered:
            if len(history) >= 2 and history[0].risk_of_ruin is not None and history[-1].risk_of_ruin is not None:
                delta = history[-1].risk_of_ruin - history[0].risk_of_ruin
                latest = history[-1]
                return (
                    f"Risk of ruin moved from {history[0].risk_of_ruin} to {history[-1].risk_of_ruin} "
                    f"({delta:+.4f}) across the supplied history. At the latest point, volatility state was "
                    f"{latest.volatility_state.label.value} and portfolio heat was {latest.portfolio_heat}."
                )
            if assessment is not None:
                return f"Current risk of ruin is {assessment.risk_of_ruin}."
            return "No statistical risk history or assessment supplied; cannot explain risk of ruin."

        # "why was risk reduced", "why was this trade statistically high
        # risk", "what statistical factors contributed" — all answered by
        # the same signal rundown over an already-produced assessment.
        if assessment is None:
            return "No statistical risk assessment supplied to answer this question."
        return (
            f"Statistical recommendation: {assessment.statistical_recommendation.value} "
            f"(confidence {assessment.confidence_score}). Contributing signals — "
            f"volatility: {assessment.volatility_state.label.value} "
            f"(ratio {assessment.volatility_state.ratio_to_average}); "
            f"correlation: most concentrated bucket {assessment.correlation_state.most_concentrated_bucket} "
            f"({assessment.correlation_state.max_bucket_concentration_count} position(s)); "
            f"portfolio heat: {assessment.portfolio_heat}; risk of ruin: {assessment.risk_of_ruin}; "
            f"probability of drawdown: {assessment.probability_of_drawdown}."
        )


__all__ = ["ExplainableDecisionEngine"]
