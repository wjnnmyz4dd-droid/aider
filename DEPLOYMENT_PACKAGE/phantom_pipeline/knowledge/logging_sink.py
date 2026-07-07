"""Structured logging for the Knowledge & RAG subsystem (`ADR-020`).
Structured logging only — no `print()`. A logging failure never
propagates into or alters engine behavior (mirrors every prior stage's
own `logging_sink.py` discipline).
"""

from __future__ import annotations

import logging

from .models import KnowledgeDocument, TradeMemoryRecord

logger = logging.getLogger("phantom_pipeline.knowledge")


def _safe_log(level: int, msg: str, extra: dict) -> None:
    try:
        logger.log(level, msg, extra=extra)
    except Exception:
        pass


def log_document_ingested(document: KnowledgeDocument, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "knowledge.document_ingested",
        {
            "document_id": document.document_id,
            "kind": document.kind.value,
            "content_hash": document.content_hash,
            "timestamp": document.ingested_at.isoformat(),
        },
    )


def log_trade_recorded(record: TradeMemoryRecord, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "knowledge.trade_recorded",
        {
            "trace_id": record.trace_id,
            "symbol": record.symbol,
            "strategy_id": record.strategy_id,
            "timestamp": record.collected_at.isoformat(),
        },
    )


def log_search_performed(query_text: str, result_count: int, latency_seconds: float, level: int = logging.INFO) -> None:
    _safe_log(
        level,
        "knowledge.search_performed",
        {
            "query_text": query_text,
            "result_count": result_count,
            "latency_seconds": latency_seconds,
        },
    )


__all__ = ["log_document_ingested", "log_trade_recorded", "log_search_performed"]
