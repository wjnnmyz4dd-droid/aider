"""Missing-event and schema-validation detection (ADR-010 §6, §12).

"Nothing may be omitted" (Hard Rules): a `TradeProvenanceRecord` missing
any field expected given how far its trade progressed, or holding an
object whose `schema_version` this build does not recognize, is a
reportable defect — never silently stored, and never silently accepted,
as if complete/valid. Every check below is independent and all are
always evaluated (mirroring `compliance_engine.checks`/`execution_
validator.checks`'s "no short-circuit, full audit trail" discipline,
applied here to completeness rather than a live pass/fail gate) — the
full set of gaps is reported together, not just the first one found.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..compliance_engine.models import Verdict as ComplianceVerdict
from ..execution_validator.models import Verdict as ExecutionVerdict
from .models import MissingEventReport, TradeProvenanceRecord

SUPPORTED_SCHEMA_VERSIONS = (1,)


def _schema_mismatch(label: str, obj) -> Optional[str]:
    if obj is None:
        return None
    if getattr(obj, "schema_version", None) not in SUPPORTED_SCHEMA_VERSIONS:
        return f"{label}:unsupported_schema_version"
    return None


def detect_issues(record: TradeProvenanceRecord, now: datetime) -> Optional[MissingEventReport]:
    missing: List[str] = []

    if record.candidate is not None and record.scanner_observation is None:
        missing.append("scanner_observation")
    if record.score_result is not None and record.candidate is None:
        missing.append("candidate")
    if record.risk_decision is not None and record.score_result is None:
        missing.append("score_result")
    if record.compliance_decision is not None and record.risk_decision is None:
        missing.append("risk_decision")
    if record.execution_decision is not None and record.compliance_decision is None:
        missing.append("compliance_decision")
    if record.compliance_decision is not None and record.compliance_decision.verdict == ComplianceVerdict.APPROVE and record.execution_decision is None:
        missing.append("execution_decision")
    if record.execution_decision is not None and record.execution_decision.verdict == ExecutionVerdict.APPROVE and not record.broker_events:
        missing.append("broker_events")
    if record.fill_reports and not record.broker_events:
        missing.append("broker_events")
    if record.fill_reports and not record.position_updates:
        missing.append("position_updates")

    schema_checks = (
        _schema_mismatch("scanner_observation", record.scanner_observation),
        _schema_mismatch("candidate", record.candidate),
        _schema_mismatch("score_result", record.score_result),
        _schema_mismatch("risk_decision", record.risk_decision),
        _schema_mismatch("compliance_decision", record.compliance_decision),
        _schema_mismatch("execution_decision", record.execution_decision),
    )
    for schema_issue in schema_checks:
        if schema_issue is not None:
            missing.append(schema_issue)

    if not missing:
        return None
    return MissingEventReport(
        trace_id=record.trace_id,
        missing_fields=tuple(missing),
        detail=f"{len(missing)} issue(s) detected for trace_id={record.trace_id}",
        timestamp=now,
    )
