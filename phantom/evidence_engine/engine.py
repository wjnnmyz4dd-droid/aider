"""`EvidenceEngine` -- the Evidence Engine's orchestrator (Phase 2A).

Wires every analysis module together into one call:
`evaluate(symbol, bars)` -> `EvidenceReport`. Computes market quality
evidence only -- never a trade decision (ADR-024 Hard Rule 1).

Thread safety: `EvidenceEngine` holds no per-call mutable state of its
own outside `IndicatorCache` (already internally locked, see
`indicators.py`) and `EvidenceEngineMetrics` (already internally
locked). `evaluate()` may therefore be called concurrently, from many
threads, against one shared `EvidenceEngine` instance, without
corrupting state or recomputing the same indicator twice for the same
symbol/bar-set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from .candlesticks import recognize_patterns
from .config import EvidenceEngineConfig
from .explainability import build_evidence_report
from .indicators import IndicatorCache, IndicatorRegistry
from .liquidity import analyze_liquidity
from .logging_sink import log_evidence_report
from .metrics import EvidenceEngineMetrics
from .models import Bar, EvidenceReport, PairRanking, PatternContext, SwingType
from .ranking import rank_pairs
from .scoring import compute_component_scores, compute_evidence_score
from .session import analyze_session
from .structure import analyze_market_structure
from .trend import classify_trend
from .volatility import analyze_volatility


def _derive_pattern_contexts(bar_count: int, swings: Sequence) -> Tuple[PatternContext, ...]:
    """A bar exactly at a swing low's index is, by definition, a local
    down-extreme (`AT_DOWNTREND_EXTREME`); exactly at a swing high, a
    local up-extreme (`AT_UPTREND_EXTREME`). Every other bar defaults to
    `MID_RANGE` -- not `UNKNOWN`, since the engine always has enough
    context (the swing set) to make this call once bars exist."""
    contexts: List[PatternContext] = [PatternContext.MID_RANGE] * bar_count
    for swing in swings:
        if 0 <= swing.index < bar_count:
            contexts[swing.index] = (
                PatternContext.AT_DOWNTREND_EXTREME if swing.swing_type == SwingType.LOW else PatternContext.AT_UPTREND_EXTREME
            )
    return tuple(contexts)


class EvidenceEngine:
    def __init__(
        self,
        config: EvidenceEngineConfig,
        registry: Optional[IndicatorRegistry] = None,
        metrics: Optional[EvidenceEngineMetrics] = None,
    ) -> None:
        self.config = config
        self.registry = registry or IndicatorRegistry()
        self.cache = IndicatorCache(config.indicator_cache_max_entries)
        self.metrics = metrics

    def evaluate(self, symbol: str, bars: Sequence[Bar], now: Optional[datetime] = None) -> EvidenceReport:
        if not bars:
            raise ValueError("evaluate() requires at least one bar")
        now = now or bars[-1].timestamp

        structure_result = analyze_market_structure(bars, self.config)
        liquidity_result = analyze_liquidity(bars, structure_result.swings, self.config)
        contexts = _derive_pattern_contexts(len(bars), structure_result.swings)
        candlestick_matches = recognize_patterns(bars, self.config, contexts)
        volatility_state = analyze_volatility(bars, self.config)
        trend = classify_trend(structure_result, volatility_state, self.config)
        session_state = analyze_session(now, self.config)

        components = compute_component_scores(
            structure_result, liquidity_result, candlestick_matches, trend, volatility_state, session_state, self.config
        )
        evidence_score = compute_evidence_score(components)
        report = build_evidence_report(symbol, now, evidence_score)

        log_evidence_report(report)
        if self.metrics is not None:
            self.metrics.record_evaluation()
        return report

    def evaluate_batch(
        self, pairs: Dict[str, Sequence[Bar]], now: Optional[datetime] = None
    ) -> Tuple[PairRanking, ...]:
        """Evaluates every pair (in a fixed, sorted-by-symbol order --
        deterministic regardless of dict insertion order) and returns
        them ranked highest score first. Sequential, not parallel: the
        thread-safety guarantee above is for *external* concurrent
        callers of `evaluate()`, not a promise that this method spawns
        its own worker threads."""
        reports = [self.evaluate(symbol, bars, now) for symbol, bars in sorted(pairs.items())]
        if self.metrics is not None:
            self.metrics.record_batch_evaluation()
        return rank_pairs(reports)


__all__ = ["EvidenceEngine"]
