"""Explainability (ADR-024 §1 "Explainability").

Turns an already-computed `EvidenceScore` into the human-readable
`EvidenceReport` fields: strengths, weaknesses, and a confidence
explanation. Adds no new evidence and recomputes nothing -- it only
narrates the `ComponentScore`s it's given.
"""

from __future__ import annotations

from datetime import datetime

from .models import EvidenceReport, EvidenceScore

_STRENGTH_THRESHOLD = 70.0
_WEAKNESS_THRESHOLD = 30.0


def build_evidence_report(symbol: str, generated_at: datetime, score: EvidenceScore) -> EvidenceReport:
    strengths = tuple(
        f"{c.name}: {c.reason} (score={c.value:.1f})"
        for c in sorted(score.components, key=lambda c: -c.value)
        if c.value >= _STRENGTH_THRESHOLD
    )
    weaknesses = tuple(
        f"{c.name}: {c.reason} (score={c.value:.1f})"
        for c in sorted(score.components, key=lambda c: c.value)
        if c.value <= _WEAKNESS_THRESHOLD
    )

    average_confidence = sum(c.confidence for c in score.components) / len(score.components)
    weakest = min(score.components, key=lambda c: c.confidence)
    confidence_explanation = (
        f"Average confidence {average_confidence:.2f} across {len(score.components)} independent "
        f"components; lowest-confidence component is '{weakest.name}' at {weakest.confidence:.2f} "
        f"({weakest.reason})."
    )

    return EvidenceReport(
        symbol=symbol,
        generated_at=generated_at,
        score=score,
        strengths=strengths,
        weaknesses=weaknesses,
        confidence_explanation=confidence_explanation,
    )


__all__ = ["build_evidence_report"]
