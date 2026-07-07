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

from datetime import datetime
from typing import Tuple

from ..knowledge import SearchResult, SemanticSearchService
from ..paper_trading import PeriodReport
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


__all__ = ["ExplainableDecisionEngine"]
