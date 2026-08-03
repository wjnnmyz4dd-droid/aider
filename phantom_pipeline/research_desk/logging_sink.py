"""Structured logging for the Phantom AI Research Desk (`ADR-021`).
Structured logging only — no `print()`. A logging failure never
propagates into or alters agent behavior.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("phantom_pipeline.research_desk")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_market_report_generated(report_id: str, period_kind: str, level: int = logging.INFO) -> None:
    _safe_log(level, "research_desk.market_report_generated", {"report_id": report_id, "period_kind": period_kind})


def log_debate_thesis_generated(symbol: str, confidence_score: float, level: int = logging.INFO) -> None:
    _safe_log(level, "research_desk.debate_thesis_generated", {"symbol": symbol, "confidence_score": confidence_score})


def log_journal_entry_created(trace_id: str, level: int = logging.INFO) -> None:
    _safe_log(level, "research_desk.journal_entry_created", {"trace_id": trace_id})


def log_question_asked(question: str, result_count: int, level: int = logging.INFO) -> None:
    _safe_log(level, "research_desk.question_asked", {"question": question, "result_count": result_count})


__all__ = [
    "log_market_report_generated",
    "log_debate_thesis_generated",
    "log_journal_entry_created",
    "log_question_asked",
]
