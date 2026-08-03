"""`ComplianceSnapshot` assembly (ADR-028 §7): every decision -- approve,
reduce, or reject -- carries a reason, the triggered rule(s), the
original recommendation, the final recommendation, and a timestamped
audit entry (ADR-028 Hard Rule 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .models import (
    AuditEntry,
    ComplianceDecision,
    ComplianceRuleId,
    ComplianceSnapshot,
    LockRecommendation,
)


def build_compliance_snapshot(
    pair: str,
    now: datetime,
    decision: ComplianceDecision,
    original_size_r: float,
    approved_size_r: float,
    reason: str,
    triggered_rules: Tuple[ComplianceRuleId, ...],
    warnings: Tuple[str, ...],
    compliance_score: float,
    lock_recommendation: Optional[LockRecommendation],
) -> ComplianceSnapshot:
    reduction_pct = 0.0 if original_size_r <= 0 else max(0.0, (original_size_r - approved_size_r) / original_size_r * 100.0)
    audit_entry = AuditEntry(
        pair=pair, decision=decision, triggered_rules=triggered_rules,
        original_size_r=original_size_r, final_size_r=approved_size_r, timestamp=now, reason=reason,
    )
    ready_for_bridge = decision != ComplianceDecision.REJECT and approved_size_r > 0

    return ComplianceSnapshot(
        pair=pair, generated_at=now, decision=decision, approved_size_r=approved_size_r,
        original_size_r=original_size_r, reduction_pct=reduction_pct, reason=reason,
        triggered_rules=triggered_rules, warnings=warnings, audit_entry=audit_entry,
        compliance_score=compliance_score, lock_recommendation=lock_recommendation,
        ready_for_bridge=ready_for_bridge,
    )


__all__ = ["build_compliance_snapshot"]
