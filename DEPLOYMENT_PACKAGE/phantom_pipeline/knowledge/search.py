"""Semantic search convenience API (`ADR-020` §3) — the example-question-
shaped methods (`find_winners`, `find_losers`, etc.). Every method reads
already-stored `TradeMemoryRecord`s or delegates to `Retriever`; nothing
here recomputes a statistic `AnalyticsEngine`/`ReportGenerator` already
own (`ADR-020` Hard Rule 7).
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from .memory import TradeMemoryStore
from .models import SearchResult, TradeMemoryRecord, SearchQuery
from .retriever import Retriever


def trade_to_text(record: TradeMemoryRecord) -> str:
    """The same free-text representation of a trade used both when
    embedding it for storage and when embedding a `find_similar_trades`
    query — keeping both sides of that comparison built the same way."""
    parts = [
        record.symbol or "",
        record.direction.value if record.direction is not None else "",
        record.market_regime or "",
        record.strategy_id or "",
        " ".join(record.sessions),
        record.why_trade_happened,
        record.why_trade_skipped or "",
        " ".join(record.rule_explanations),
    ]
    return " ".join(p for p in parts if p)


class SemanticSearchService:
    def __init__(self, retriever: Retriever, trade_memory_store: TradeMemoryStore) -> None:
        self._retriever = retriever
        self._trade_memory_store = trade_memory_store

    def search(self, text: str, top_k: int = 10, filters: Optional[dict] = None) -> Tuple[SearchResult, ...]:
        return self._retriever.retrieve(SearchQuery(text=text, top_k=top_k, filters=filters or {}))

    def find_winners(self, symbol: Optional[str] = None) -> Tuple[TradeMemoryRecord, ...]:
        records = self._trade_memory_store.find_by(symbol=symbol)
        return tuple(r for r in records if r.realized_pnl is not None and r.realized_pnl > 0)

    def find_losers(self, symbol: Optional[str] = None, session: Optional[str] = None) -> Tuple[TradeMemoryRecord, ...]:
        records = self._trade_memory_store.find_by(symbol=symbol, session=session)
        return tuple(r for r in records if r.realized_pnl is not None and r.realized_pnl < 0)

    def find_similar_trades(self, trace_id: str, top_k: int = 5) -> Tuple[TradeMemoryRecord, ...]:
        source = self._trade_memory_store.get(trace_id)
        if source is None:
            return ()
        results = self.search(trade_to_text(source), top_k=top_k + 1)
        similar = [r.trade for r in results if r.trade is not None and r.trade.trace_id != trace_id]
        return tuple(similar[:top_k])

    def find_by_setup_pattern(self, keyword: str) -> Tuple[TradeMemoryRecord, ...]:
        """Literal, case-insensitive keyword match over each trade's own
        already-generated explanation text (e.g. \"BOS\", \"liquidity
        sweep\", \"CHOCH\") — a real, non-fabricated match over recorded
        text, complementary to `search()`'s vector-based retrieval."""
        keyword_lower = keyword.lower()
        return tuple(
            record
            for record in self._trade_memory_store.all()
            if keyword_lower in record.why_trade_happened.lower()
            or any(keyword_lower in explanation.lower() for explanation in record.rule_explanations)
        )

    def find_drawdowns_over(
        self, threshold_pct: float, drawdown_pct_fn: Callable[[TradeMemoryRecord], Optional[float]]
    ) -> Tuple[TradeMemoryRecord, ...]:
        """No canonical per-trade drawdown field exists on
        `TradeProvenanceRecord` today (`account_snapshots` is loosely
        typed `Tuple[Any, ...]`, per `analytics.models`' own documented
        gap) — `drawdown_pct_fn` is a caller-supplied accessor (e.g.
        wired to `paper_trading.AccountTracker`'s own drawdown
        computation) so this method never guesses at an undefined
        field."""
        results = []
        for record in self._trade_memory_store.all():
            value = drawdown_pct_fn(record)
            if value is not None and value > threshold_pct:
                results.append(record)
        return tuple(results)


__all__ = ["SemanticSearchService", "trade_to_text"]
