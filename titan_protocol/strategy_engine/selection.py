"""The 6-step deterministic selection cascade (ADR-026 §1 "Strategy
Selection" / Hard Rule 6). Only `QUALIFIED` results ever compete. Each
step narrows the candidate set to those within `config.score_tie_tolerance`
of the best value at that step; if exactly one remains, it wins
immediately. If every step leaves more than one candidate, the setup is
rejected -- never randomized, never an arbitrary first-registered
tiebreak.

Steps 3 ("historical strategy ranking") and 4 ("portfolio
concentration") are explicitly placeholders per the task spec -- no
Research & Learning Engine or Portfolio Statistical Risk Engine exists
yet to supply real values, so both are documented no-ops (every
candidate ties, the cascade moves on) rather than fabricated data.
Steps 5-6 (liquidity quality, news risk) are pair-level facts shared by
every strategy competing for the same pair, so in this single-pair
`evaluate()` scope they typically leave every candidate tied too --
implemented faithfully anyway, since they are the correct tiebreak in a
future multi-pair portfolio-selection scope this phase does not build.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, TypeVar

from titan_protocol.evidence_engine.models import EvidenceSnapshot
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot

from .config import StrategyEngineConfig
from .models import QualificationResult, QualificationStatus, WinningStrategy

T = TypeVar("T")


def _narrow_by(candidates: Sequence[T], key: Callable[[T], float], tolerance: float) -> List[T]:
    if not candidates:
        return []
    best = max(key(c) for c in candidates)
    return [c for c in candidates if best - key(c) <= tolerance]


def select_winning_strategy(
    qualifications: Sequence[QualificationResult],
    evidence: EvidenceSnapshot,
    market_intelligence: MarketIntelligenceSnapshot,
    config: StrategyEngineConfig,
) -> Optional[WinningStrategy]:
    candidates = [q for q in qualifications if q.status == QualificationStatus.QUALIFIED]
    if not candidates:
        return None

    # Step 1: highest Qualification Score.
    candidates = _narrow_by(candidates, lambda q: q.score, config.score_tie_tolerance)
    if len(candidates) == 1:
        return WinningStrategy(candidates[0].strategy_id, candidates[0])

    # Step 2: highest Evidence alignment -- this strategy's own
    # confidence already reflects how strongly the Evidence Snapshot's
    # components corroborate its qualification.
    candidates = _narrow_by(candidates, lambda q: q.confidence, config.score_tie_tolerance / 100.0)
    if len(candidates) == 1:
        return WinningStrategy(candidates[0].strategy_id, candidates[0])

    # Step 3: historical strategy ranking (future input) -- placeholder,
    # no-op until a Research & Learning Engine exists to supply this.
    # Step 4: portfolio concentration (placeholder only) -- no-op until
    # a Portfolio Statistical Risk Engine exists to supply this.

    # Step 5: highest liquidity quality (pair-level fact).
    liquidity_score = market_intelligence.pair_safety.liquidity.liquidity_score
    candidates = _narrow_by(candidates, lambda _q: liquidity_score, config.score_tie_tolerance)
    if len(candidates) == 1:
        return WinningStrategy(candidates[0].strategy_id, candidates[0])

    # Step 6: lowest news risk (pair-level fact) -- "lowest," so narrow
    # by the highest *negated* news score, i.e. by -news_score.
    news_score = market_intelligence.pair_safety.news.news_score
    candidates = _narrow_by(candidates, lambda _q: -news_score, config.score_tie_tolerance)
    if len(candidates) == 1:
        return WinningStrategy(candidates[0].strategy_id, candidates[0])

    # Still tied after all six steps: reject, never randomize.
    return None


__all__ = ["select_winning_strategy"]
