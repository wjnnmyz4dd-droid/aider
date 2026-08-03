"""Evidence Score -> confidence tier -> base R lookup (ADR-027 Hard Rule 3).

This schedule is owned exclusively by the Risk Engine -- no other
package defines or overrides it (ADR-027 §3).
"""

from __future__ import annotations

from typing import Optional

from .config import RiskEngineConfig
from .models import ConfidenceTier


def confidence_tier_for_evidence_score(score: float, config: RiskEngineConfig) -> Optional[ConfidenceTier]:
    """`None` only if `score` is below every configured tier's floor --
    should be unreachable downstream of `gate.py`'s 65-point check with
    the default schedule, but this function makes no such assumption
    itself (it is independently testable at any score)."""

    return config.confidence_tier_for_score(score)


__all__ = ["confidence_tier_for_evidence_score"]
