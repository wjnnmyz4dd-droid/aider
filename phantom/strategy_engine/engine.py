"""`StrategyEngine` -- the Strategy Engine's orchestrator (Phase 2C).

Consumes an `EvidenceSnapshot` (ADR-024) and a `MarketIntelligenceSnapshot`
(ADR-025) for one pair, runs every registered strategy's `qualify()`,
runs the deterministic selection cascade, and produces a
`StrategySnapshot`. No sizing, no execution (ADR-026 Hard Rule 1); the
winning strategy's `trade_intent` (BUY/SELL/NONE, ADR-026 Amendment 1)
is the one narrow exception -- a directional conclusion, never a size
or order.

Thread safety: `StrategyEngine` holds no per-call mutable state.
`StrategyRegistry` is populated once at construction and never mutated
afterward (ADR-026 Hard Rule 5) -- concurrent reads of an unchanging
dict are safe under CPython's GIL. `evaluate()` may be called
concurrently from many threads against one shared instance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple

from phantom.evidence_engine.models import EvidenceSnapshot
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from .config import StrategyEngineConfig
from .explainability import build_strategy_snapshot
from .logging_sink import log_strategy_snapshot
from .metrics import StrategyEngineMetrics
from .models import StrategySnapshot
from .selection import select_winning_strategy
from .strategies import StrategyRegistry, build_default_registry


class StrategyEngine:
    def __init__(
        self,
        config: StrategyEngineConfig,
        registry: Optional[StrategyRegistry] = None,
        metrics: Optional[StrategyEngineMetrics] = None,
    ) -> None:
        self.config = config
        # `is not None`, not `registry or ...` -- StrategyRegistry defines
        # `__len__`, so an explicitly-passed *empty* registry would be
        # falsy and silently replaced by the default one otherwise.
        self.registry = registry if registry is not None else build_default_registry()
        self.metrics = metrics

    def evaluate(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        now: Optional[datetime] = None,
    ) -> StrategySnapshot:
        if evidence.report.symbol != pair:
            raise ValueError(f"evidence.report.symbol ({evidence.report.symbol!r}) does not match pair ({pair!r})")
        if market_intelligence.pair != pair:
            raise ValueError(f"market_intelligence.pair ({market_intelligence.pair!r}) does not match pair ({pair!r})")
        now = now or evidence.report.generated_at

        qualifications = tuple(
            strategy.qualify(pair, evidence, market_intelligence, self.config)
            for strategy in self.registry.all()
        )
        winning_strategy = select_winning_strategy(qualifications, evidence, market_intelligence, self.config)
        snapshot = build_strategy_snapshot(pair, now, qualifications, winning_strategy, evidence, market_intelligence)

        log_strategy_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            if winning_strategy is not None:
                self.metrics.record_selection()
            else:
                self.metrics.record_rejection()
        return snapshot

    def evaluate_batch(
        self,
        pairs: Dict[str, Tuple[EvidenceSnapshot, MarketIntelligenceSnapshot]],
        now: Optional[datetime] = None,
    ) -> Tuple[StrategySnapshot, ...]:
        """Evaluates every pair, sorted by symbol for determinism.
        `pairs[pair]` is `(evidence_snapshot, market_intelligence_snapshot)`."""
        results = tuple(
            self.evaluate(pair, evidence, market_intelligence, now)
            for pair, (evidence, market_intelligence) in sorted(pairs.items())
        )
        if self.metrics is not None:
            self.metrics.record_batch_evaluation()
        return results


__all__ = ["StrategyEngine"]
