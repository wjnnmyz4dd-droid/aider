"""Shared test-only fixtures for the System Reliability Engine test
suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from titan_protocol.reliability.config import ReliabilityConfig
from titan_protocol.runtime.models import CycleOutcome, CycleReport, CycleStage, RuntimeAuditRecord
from titan_protocol.strategy_engine.models import TradeIntent

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)


def make_config(**overrides) -> ReliabilityConfig:
    return ReliabilityConfig(**overrides)


def make_audit_record(
    pair: str = "EURUSD",
    outcome: CycleOutcome = CycleOutcome.SUBMITTED,
    cycle_id: str = "CYCLE-1",
    now: datetime = T0,
    duration_ms: float = 5.0,
    stage_reached: Optional[CycleStage] = CycleStage.BRIDGE,
) -> RuntimeAuditRecord:
    return RuntimeAuditRecord(
        cycle_id=cycle_id, pair=pair, profile_id="test_profile", configuration_version=1,
        started_at=now, ended_at=now, duration_ms=duration_ms, outcome=outcome, stage_reached=stage_reached,
        evidence_id=f"{pair}:{now.isoformat()}", selected_strategy=None, trade_intent=TradeIntent.NONE,
        risk_approved=None, compliance_decision=None, bridge_error=None, reasons=(), stage_timings=(),
        engine_versions=(),
    )


def make_cycle_report(records: Sequence[RuntimeAuditRecord], cycle_id: str = "CYCLE-1", now: datetime = T0) -> CycleReport:
    return CycleReport(cycle_id=cycle_id, started_at=now, ended_at=now, duration_ms=sum(r.duration_ms for r in records), records=tuple(records))


__all__ = ["T0", "make_config", "make_audit_record", "make_cycle_report"]
