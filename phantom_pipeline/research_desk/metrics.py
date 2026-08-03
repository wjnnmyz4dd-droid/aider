"""Research Desk-only metrics surface (`ADR-021` §3). Export-only,
additive — recording a metric has zero effect on any returned output,
matching every prior stage's own metrics module discipline.
"""

from __future__ import annotations

from typing import List


class ResearchDeskMetrics:
    def __init__(self) -> None:
        self._market_reports_generated_count: int = 0
        self._debate_theses_generated_count: int = 0
        self._trade_theses_generated_count: int = 0
        self._journal_entries_created_count: int = 0
        self._institutional_reviews_generated_count: int = 0
        self._questions_asked_count: int = 0
        self._question_latencies_seconds: List[float] = []

    def record_market_report_generated(self) -> None:
        self._market_reports_generated_count += 1

    def record_debate_thesis_generated(self) -> None:
        self._debate_theses_generated_count += 1

    def record_trade_thesis_generated(self) -> None:
        self._trade_theses_generated_count += 1

    def record_journal_entry_created(self) -> None:
        self._journal_entries_created_count += 1

    def record_institutional_review_generated(self) -> None:
        self._institutional_reviews_generated_count += 1

    def record_question_asked(self, latency_seconds: float) -> None:
        self._questions_asked_count += 1
        self._question_latencies_seconds.append(latency_seconds)

    @property
    def market_reports_generated_count(self) -> int:
        return self._market_reports_generated_count

    @property
    def debate_theses_generated_count(self) -> int:
        return self._debate_theses_generated_count

    @property
    def trade_theses_generated_count(self) -> int:
        return self._trade_theses_generated_count

    @property
    def journal_entries_created_count(self) -> int:
        return self._journal_entries_created_count

    @property
    def institutional_reviews_generated_count(self) -> int:
        return self._institutional_reviews_generated_count

    @property
    def questions_asked_count(self) -> int:
        return self._questions_asked_count

    @property
    def average_question_latency_seconds(self) -> float:
        if not self._question_latencies_seconds:
            return 0.0
        return sum(self._question_latencies_seconds) / len(self._question_latencies_seconds)


__all__ = ["ResearchDeskMetrics"]
