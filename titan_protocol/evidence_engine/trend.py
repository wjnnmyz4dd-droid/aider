"""Trend analysis: the 6-state classification (ADR-024 §1 "Trend
Analysis") -- trending up/down, range, compression, expansion,
reversal.

Built on top of `structure.py`'s swing-sequence trend read and
`volatility.py`'s expansion/compression flags; never recomputes either.
Priority order (checked top to bottom, first match wins -- documented
here so the decision is auditable, not a hidden tie-break):

1. The most recent structure event is a CHOCH -> `REVERSAL`. A change of
   character firing right now outranks everything else -- it is, by
   definition, evidence the prior trend read no longer holds.
2. Volatility is in compression -> `COMPRESSION`.
3. Volatility is in expansion -> `EXPANSION`.
4. Otherwise, the structural trend read from swing sequence:
   `TRENDING_UP` / `TRENDING_DOWN` / `RANGE`.
"""

from __future__ import annotations

from .config import EvidenceEngineConfig
from .models import MarketStructureResult, StructureEventType, TrendClassification, VolatilityState


def classify_trend(
    structure_result: MarketStructureResult,
    volatility_state: VolatilityState,
    config: EvidenceEngineConfig,
) -> TrendClassification:
    if structure_result.events:
        latest_event = max(structure_result.events, key=lambda e: e.confirmed_index)
        if latest_event.event_type == StructureEventType.CHOCH:
            return TrendClassification.REVERSAL

    if volatility_state.is_compression:
        return TrendClassification.COMPRESSION

    if volatility_state.is_expansion:
        return TrendClassification.EXPANSION

    return structure_result.trend


__all__ = ["classify_trend"]
