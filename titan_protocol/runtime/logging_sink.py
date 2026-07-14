"""Structured logging for the Runtime Orchestrator.

A logging failure never propagates into or alters this package's
return value -- same discipline as every other engine's logging_sink
this session. No silent failures (ADR-031 SS7): every cycle is logged,
including a FAILED outcome.
"""

from __future__ import annotations

import logging

from .models import RuntimeAuditRecord

logger = logging.getLogger("titan_protocol.runtime")


def _safe_log(level: int, message: str, extra: dict) -> None:
    try:
        logger.log(level, message, extra=extra)
    except Exception:
        pass


def log_runtime_audit_record(record: RuntimeAuditRecord) -> None:
    level = logging.ERROR if record.outcome.name == "FAILED" else logging.INFO
    _safe_log(
        level,
        "runtime_audit_record",
        {
            "cycle_id": record.cycle_id,
            "pair": record.pair,
            "profile_id": record.profile_id,
            "outcome": record.outcome.value,
            "stage_reached": record.stage_reached.value if record.stage_reached else None,
            "duration_ms": record.duration_ms,
            # Final Release Hardening (requirement 4) -- every field the
            # record itself already carries, surfaced in the text log
            # too (previously only visible via the in-memory object).
            "decision_id": record.decision_id,
            "configuration_version": record.configuration_version,
            "config_schema_version": record.config_schema_version,
            "timeframe": record.timeframe,
            "evidence_id": record.evidence_id,
            "evidence_summary": record.evidence_summary,
            "market_intelligence_summary": record.market_intelligence_summary,
            "selected_strategy": record.selected_strategy.value if record.selected_strategy else None,
            "trade_intent": record.trade_intent.value,
            "risk_approved": record.risk_approved,
            "risk_reasons": record.risk_reasons,
            "compliance_decision": record.compliance_decision.value if record.compliance_decision else None,
            "compliance_triggered_rules": record.compliance_triggered_rules,
            "compliance_lock_trigger": record.compliance_lock_trigger,
            "compliance_lock_reason": record.compliance_lock_reason,
            "bridge_error": record.bridge_error.value if record.bridge_error else None,
            "bridge_correlation_id": record.bridge_correlation_id,
            "reasons": record.reasons,
            "snapshot_hash": record.snapshot_hash,
            "decision_fingerprint": record.decision_fingerprint,
        },
    )


__all__ = ["log_runtime_audit_record"]
