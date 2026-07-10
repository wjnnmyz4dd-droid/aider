"""`MarketIntelligenceEngine` -- the Market Intelligence Engine's
orchestrator (Phase 2B).

Wires every analysis module together into one call:
`evaluate(pair, evidence, ...)` -> `MarketIntelligenceSnapshot`.
Consumes an `EvidenceReport` (ADR-024) read-only and this engine's own
directly-supplied news/liquidity/market-safety inputs; produces a
`MarketIntelligenceSnapshot` and nothing else -- zero trade, risk,
strategy, or compliance authority (ADR-025 Hard Rule 6).

Thread safety: `MarketIntelligenceEngine` holds no per-call mutable
state of its own outside `_NewsFeedCache` (internally locked) and
`MarketIntelligenceMetrics` (internally locked) -- `evaluate()` may be
called concurrently from many threads against one shared instance.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime
from typing import Dict, Optional, Sequence, Tuple

from phantom.evidence_engine.models import EvidenceReport

from .config import MarketIntelligenceConfig
from .explainability import build_explanation
from .liquidity_intelligence import evaluate_liquidity
from .logging_sink import log_market_intelligence_snapshot
from .market_safety import evaluate_market_safety
from .metrics import MarketIntelligenceMetrics
from .models import (
    MarketIntelligenceSnapshot,
    MarketSafetyInputs,
    NewsEvent,
    PairNewsIntelligence,
    PegPolicyStatus,
)
from .news import build_pair_news_intelligence
from .peg_policy import PegPolicyRegistry
from .scoring import build_pair_safety, build_trade_readiness
from .session_intelligence import evaluate_session


class _NewsFeedCache:
    """Bounded, deterministic cache over the (pair, minute, events)
    key -- avoids re-filtering/re-bucketing the same news feed snapshot
    for the same pair within the same minute across repeated calls
    (ADR-025 §12 "cache external data responsibly"). Oldest evicted
    first once full, same discipline as the Evidence Engine's
    `IndicatorCache` (Phase 2A) -- no LRU-by-access, no randomness."""

    def __init__(self, max_entries: int) -> None:
        self._max_entries = max_entries
        self._store: "OrderedDict[Tuple, PairNewsIntelligence]" = OrderedDict()
        self._lock = threading.Lock()

    def get_or_compute(
        self, pair: str, events: Sequence[NewsEvent], now: datetime, config: MarketIntelligenceConfig
    ) -> PairNewsIntelligence:
        key = (pair, now.replace(second=0, microsecond=0), tuple(events))
        with self._lock:
            cached = self._store.get(key)
            if cached is not None:
                return cached
        result = build_pair_news_intelligence(pair, events, now, config)
        with self._lock:
            self._store.setdefault(key, result)
            if len(self._store) > self._max_entries:
                self._store.popitem(last=False)
            return self._store[key]

    def size(self) -> int:
        with self._lock:
            return len(self._store)


def _untrusted_news_intelligence(pair: str) -> PairNewsIntelligence:
    """Fail-closed path: if the caller cannot vouch for the news feed
    (`news_feed_trusted=False`), never assume "no news" -- assume the
    worst (blackout) rather than silently treating an untrustworthy feed
    as safe (ADR-025 Hard Rule 5)."""
    return PairNewsIntelligence(
        pair=pair, upcoming_events=(), active_events=(), recent_events=(),
        news_score=0.0, blackout_active=True, blackout_reason="news feed untrusted -- failing closed",
    )


class MarketIntelligenceEngine:
    def __init__(
        self,
        config: MarketIntelligenceConfig,
        peg_policy_registry: Optional[PegPolicyRegistry] = None,
        metrics: Optional[MarketIntelligenceMetrics] = None,
    ) -> None:
        self.config = config
        self.peg_policy_registry = peg_policy_registry or PegPolicyRegistry()
        self.metrics = metrics
        self._news_cache = _NewsFeedCache(config.news_feed_cache_max_entries)

    def evaluate(
        self,
        pair: str,
        evidence: EvidenceReport,
        events: Sequence[NewsEvent],
        current_spread: float,
        average_spread: float,
        market_safety_inputs: MarketSafetyInputs,
        now: Optional[datetime] = None,
        news_feed_trusted: bool = True,
    ) -> MarketIntelligenceSnapshot:
        if evidence.symbol != pair:
            raise ValueError(f"evidence.symbol ({evidence.symbol!r}) does not match pair ({pair!r})")
        now = now or evidence.generated_at

        if news_feed_trusted:
            news = self._news_cache.get_or_compute(pair, events, now, self.config)
            if self.metrics is not None:
                self.metrics.record_cache_access()
        else:
            news = _untrusted_news_intelligence(pair)

        session = evaluate_session(now, self.config)
        liquidity = evaluate_liquidity(current_spread, average_spread, self.config)
        market_safety = evaluate_market_safety(now, market_safety_inputs, self.config)
        peg_policy = self.peg_policy_registry.status_for(pair)

        pair_safety = build_pair_safety(pair, news, liquidity, session, market_safety, peg_policy, self.config)
        trade_readiness = build_trade_readiness(pair_safety, self.config)
        explanation = build_explanation(pair_safety, trade_readiness)

        snapshot = MarketIntelligenceSnapshot(
            pair=pair, generated_at=now, pair_safety=pair_safety,
            trade_readiness=trade_readiness, explanation=explanation,
        )
        log_market_intelligence_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
        return snapshot

    def evaluate_batch(
        self,
        pairs: Dict[str, EvidenceReport],
        events: Sequence[NewsEvent],
        spreads: Dict[str, Tuple[float, float]],
        market_safety_inputs: MarketSafetyInputs,
        now: Optional[datetime] = None,
        news_feed_trusted: bool = True,
    ) -> Tuple[MarketIntelligenceSnapshot, ...]:
        """Evaluates every pair, sorted by symbol for determinism.
        `spreads[pair]` is `(current_spread, average_spread)`."""
        results = []
        for pair, evidence in sorted(pairs.items()):
            current_spread, average_spread = spreads[pair]
            results.append(
                self.evaluate(
                    pair, evidence, events, current_spread, average_spread,
                    market_safety_inputs, now, news_feed_trusted,
                )
            )
        if self.metrics is not None:
            self.metrics.record_batch_evaluation()
        return tuple(results)


__all__ = ["MarketIntelligenceEngine"]
