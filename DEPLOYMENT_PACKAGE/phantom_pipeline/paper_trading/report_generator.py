"""Daily/weekly/monthly reports for the Paper Trading Runner (Phase 4).

**Reuses `AnalyticsEngine`'s existing grouping methods — never a second
grouping implementation.** `group_by_pair`/`group_by_session`/
`group_by_regime` already exist on `AnalyticsEngine` (`ADR-010` §9); this
module calls them directly and ranks the resulting groups by each group's
own already-recorded `final_outcome.realized_pnl` values (a plain sum over
an already-recorded field, the same "no aggregation beyond what's already
recorded" posture `Dashboard`/`ForwardTestEngine` already establish) —
never a parallel PnL-by-pair/session/regime computation of its own.

**One `PeriodReport` shape for all three periods.** Daily, weekly, and
monthly reports differ only in their window boundaries — not their
structure — so this module defines one report type and three thin
convenience methods (`generate_daily`/`generate_weekly`/`generate_monthly`)
that compute the appropriate window and delegate to the same
`generate()`, rather than three near-identical dataclasses (`CLAUDE.md`
§6's "three similar lines before a fourth abstraction," applied here in
the other direction: one real abstraction, not three copies of it).

**Recovery statistics are read from `ForwardTestReport`, not recomputed.**
`ForwardTestEngine` already attributes `WatchdogMetrics`' recovery
attempt/success-rate/duration numbers; this module's `PeriodReport`
references that same `ForwardTestReport` rather than reading
`WatchdogMetrics` a second time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Sequence, Tuple

from ..analytics import AnalyticsEngine, TradeProvenanceRecord
from ..analytics.models import OutcomeKind
from ..compliance_engine import ComplianceEngineMetrics
from ..execution_validator import ExecutionValidatorMetrics
from .forward_test_engine import ForwardTestEngine, ForwardTestReport
from .prop_firm_validator import PropFirmComplianceStatus

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PeriodReport:
    schema_version: int
    period_kind: str  # "DAILY" | "WEEKLY" | "MONTHLY"
    window_start: datetime
    window_end: datetime
    generated_at: datetime

    forward_test_report: ForwardTestReport
    prop_firm_status: Optional[PropFirmComplianceStatus]

    best_pair: Optional[str]
    worst_pair: Optional[str]
    best_session: Optional[str]
    worst_session: Optional[str]
    best_regime: Optional[str]
    worst_regime: Optional[str]

    biggest_winner_trace_id: Optional[str]
    biggest_winner_pnl: Optional[float]
    biggest_loser_trace_id: Optional[str]
    biggest_loser_pnl: Optional[float]

    compliance_blocks_by_check: Dict[str, int]
    execution_blocks_by_check: Dict[str, int]
    compliance_decisions_by_verdict: Dict[str, int]
    kill_switch_active: bool
    daily_lockout_active: bool


class ReportGenerator:
    def __init__(
        self,
        analytics: AnalyticsEngine,
        forward_test_engine: ForwardTestEngine,
        compliance_engine_metrics: ComplianceEngineMetrics,
        execution_validator_metrics: ExecutionValidatorMetrics,
    ) -> None:
        self._analytics = analytics
        self._forward_test_engine = forward_test_engine
        self._compliance_engine_metrics = compliance_engine_metrics
        self._execution_validator_metrics = execution_validator_metrics

    def generate_daily(
        self, records: Sequence[TradeProvenanceRecord], now: datetime,
        account_snapshot=None, prop_firm_status: Optional[PropFirmComplianceStatus] = None,
    ) -> PeriodReport:
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.generate("DAILY", records, window_start, now, now, account_snapshot, prop_firm_status)

    def generate_weekly(
        self, records: Sequence[TradeProvenanceRecord], now: datetime,
        account_snapshot=None, prop_firm_status: Optional[PropFirmComplianceStatus] = None,
    ) -> PeriodReport:
        window_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.generate("WEEKLY", records, window_start, now, now, account_snapshot, prop_firm_status)

    def generate_monthly(
        self, records: Sequence[TradeProvenanceRecord], now: datetime,
        account_snapshot=None, prop_firm_status: Optional[PropFirmComplianceStatus] = None,
    ) -> PeriodReport:
        window_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.generate("MONTHLY", records, window_start, now, now, account_snapshot, prop_firm_status)

    def generate(
        self,
        period_kind: str,
        records: Sequence[TradeProvenanceRecord],
        window_start: datetime,
        window_end: datetime,
        now: datetime,
        account_snapshot=None,
        prop_firm_status: Optional[PropFirmComplianceStatus] = None,
    ) -> PeriodReport:
        forward_test_report = self._forward_test_engine.build_report(
            records, account_snapshot, window_start, window_end, now
        )

        best_pair, worst_pair = _rank_groups(self._analytics.group_by_pair(records))
        best_session, worst_session = _rank_groups(self._analytics.group_by_session(records))
        best_regime, worst_regime = _rank_groups(self._analytics.group_by_regime(records))

        winner_id, winner_pnl, loser_id, loser_pnl = _biggest_winner_and_loser(records)

        return PeriodReport(
            schema_version=SCHEMA_VERSION,
            period_kind=period_kind,
            window_start=window_start,
            window_end=window_end,
            generated_at=now,
            forward_test_report=forward_test_report,
            prop_firm_status=prop_firm_status,
            best_pair=best_pair,
            worst_pair=worst_pair,
            best_session=best_session,
            worst_session=worst_session,
            best_regime=best_regime,
            worst_regime=worst_regime,
            biggest_winner_trace_id=winner_id,
            biggest_winner_pnl=winner_pnl,
            biggest_loser_trace_id=loser_id,
            biggest_loser_pnl=loser_pnl,
            compliance_blocks_by_check=dict(self._compliance_engine_metrics.blocks_by_check),
            execution_blocks_by_check=dict(self._execution_validator_metrics.blocks_by_check),
            compliance_decisions_by_verdict=dict(self._compliance_engine_metrics.decisions_by_verdict),
            kill_switch_active=self._compliance_engine_metrics.kill_switch_active,
            daily_lockout_active=self._compliance_engine_metrics.daily_lockout_active,
        )


def _group_total_pnl(records: Tuple[TradeProvenanceRecord, ...]) -> Optional[float]:
    pnls = [
        r.final_outcome.realized_pnl
        for r in records
        if r.final_outcome is not None
        and r.final_outcome.outcome_kind == OutcomeKind.CLOSED
        and r.final_outcome.realized_pnl is not None
    ]
    return sum(pnls) if pnls else None


def _rank_groups(groups: Dict[str, Tuple[TradeProvenanceRecord, ...]]) -> Tuple[Optional[str], Optional[str]]:
    totals = {key: _group_total_pnl(records) for key, records in groups.items()}
    totals = {key: total for key, total in totals.items() if total is not None}
    if not totals:
        return None, None
    best = max(totals, key=lambda k: totals[k])
    worst = min(totals, key=lambda k: totals[k])
    return best, worst


def _biggest_winner_and_loser(records: Sequence[TradeProvenanceRecord]):
    winner_id, winner_pnl = None, None
    loser_id, loser_pnl = None, None
    for record in records:
        if record.final_outcome is None or record.final_outcome.outcome_kind != OutcomeKind.CLOSED:
            continue
        pnl = record.final_outcome.realized_pnl
        if pnl is None:
            continue
        if winner_pnl is None or pnl > winner_pnl:
            winner_id, winner_pnl = record.trace_id, pnl
        if loser_pnl is None or pnl < loser_pnl:
            loser_id, loser_pnl = record.trace_id, pnl
    return winner_id, winner_pnl, loser_id, loser_pnl


__all__ = ["PeriodReport", "ReportGenerator"]
