"""The 65-point evidence hard gate (ADR-027 Hard Rule 1).

Deliberately the very first check `engine.py` runs: below the
configured minimum, nothing else in this package is computed --- no
exposure, no correlation, no statistics, no Monte Carlo, no sizing.
"""

from __future__ import annotations

from typing import Optional

from phantom.evidence_engine.models import EvidenceSnapshot

from .config import RiskEngineConfig
from .models import RejectionReason


def check_evidence_gate(evidence: EvidenceSnapshot, config: RiskEngineConfig) -> Optional[RejectionReason]:
    """Returns the rejection reason if the gate fails, else `None`."""

    if evidence.report.score.composite < config.minimum_evidence_score:
        return RejectionReason.INSUFFICIENT_EVIDENCE
    return None


__all__ = ["check_evidence_gate"]
