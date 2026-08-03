"""Shared graduated-band evaluation (ADR-028 §5.1-5.3) -- one function,
reused by `daily_loss.py`, `drawdown.py`, and `profit_protection.py`
rather than three near-identical implementations (CLAUDE.md §6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .models import GraduatedBand


@dataclass(frozen=True)
class BandEvaluation:
    multiplier: float
    hard_reject: bool
    label: str
    gate_failed_reason: Optional[str] = None
    gate_kind: Optional[str] = None  # "evidence" or "strategy" -- which gate failed, never inferred from text


def evaluate_graduated_bands(
    pct: float,
    bands: Tuple[GraduatedBand, ...],
    evidence_score: Optional[float] = None,
    strategy_score: Optional[float] = None,
) -> BandEvaluation:
    """Finds the band `pct` falls into (falling back to the most severe
    band if `pct` exceeds every configured range -- fail closed, never
    silently "no band matched, assume normal"). If the matched band
    declares a confidence/quality gate and the corresponding score is
    below it, the caller should treat this as a hard reject regardless
    of the band's own `multiplier` (ADR-028 §5.1: elevated bands require
    "exceptionally high confidence"/"highest-quality setups," not merely
    a smaller size)."""

    matched = bands[-1]
    for band in bands:
        if band.min_pct <= pct < band.max_pct:
            matched = band
            break

    if matched.min_evidence_score is not None and (evidence_score is None or evidence_score < matched.min_evidence_score):
        return BandEvaluation(
            multiplier=matched.multiplier, hard_reject=True, label=matched.label, gate_kind="evidence",
            gate_failed_reason=f"evidence score below required {matched.min_evidence_score:.1f} for band {matched.label!r}",
        )
    if matched.min_strategy_score is not None and (strategy_score is None or strategy_score < matched.min_strategy_score):
        return BandEvaluation(
            multiplier=matched.multiplier, hard_reject=True, label=matched.label, gate_kind="strategy",
            gate_failed_reason=f"strategy score below required {matched.min_strategy_score:.1f} for band {matched.label!r}",
        )

    return BandEvaluation(multiplier=matched.multiplier, hard_reject=matched.hard_reject, label=matched.label)


__all__ = ["BandEvaluation", "evaluate_graduated_bands"]
