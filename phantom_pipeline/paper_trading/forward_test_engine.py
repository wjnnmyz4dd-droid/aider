"""Forward-testing statistics for the Paper Trading Runner (Phase 4).

**Attribute, never fabricate — the same discipline `TEAM.md`'s AI
Systems Engineer and Quant Validation Engineer roles already establish
for this exact kind of derived-reporting layer.** Every number below is
either read directly from an already-computed object
(`analytics.models.PerformanceStatistics`, or one of the six existing
per-stage `*Metrics` objects), or a plain, transparent aggregation
(count/sum/average) over fields already present on an already-collected
`TradeProvenanceRecord` — never a second, independent implementation of
logic an engine already owns.

Fields with no honest source are reported as `None`/`0`, never a
fabricated placeholder — mirroring `data_pipeline.models.
DataQualityReport.latency_seconds`'s own "`None` means cannot be honestly
measured" precedent. Concretely, observed slippage requires both a
`MarketSnapshot` (captured at candidate time) and a `FillReport` (the
actual fill) on the same record; a record missing either is skipped, not
assumed to have zero slippage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from ..analytics import AnalyticsEngine, PerformanceStatistics, TradeProvenanceRecord
from ..execution_validator import ExecutionValidatorMetrics
from ..mt5_bridge import MT5BridgeMetrics
from ..watchdog import WatchdogMetrics
from .account_tracker import AccountSnapshot

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ForwardTestReport:
    schema_version: int
    generated_at: datetime
    window_start: datetime
    window_end: datetime

    trade_count: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    expectancy: Optional[float]
    average_rr: Optional[float]
    max_drawdown: Optional[float]

    daily_drawdown_pct: Optional[float]
    total_drawdown_pct: Optional[float]

    average_validation_latency_seconds: float
    average_broker_latency_seconds: float
    average_fill_latency_seconds: float
    average_slippage: Optional[float]
    slippage_sample_size: int

    missed_trade_count: int
    blocked_trade_count: int
    duplicate_prevention_count: int

    recovery_attempt_count: int
    recovery_success_rate: float
    average_recovery_time_seconds: float

    analytics_version: str


class ForwardTestEngine:
    def __init__(
        self,
        analytics: AnalyticsEngine,
        execution_validator_metrics: ExecutionValidatorMetrics,
        mt5_bridge_metrics: MT5BridgeMetrics,
        watchdog_metrics: WatchdogMetrics,
    ) -> None:
        self._analytics = analytics
        self._execution_validator_metrics = execution_validator_metrics
        self._mt5_bridge_metrics = mt5_bridge_metrics
        self._watchdog_metrics = watchdog_metrics

    def build_report(
        self,
        records: Sequence[TradeProvenanceRecord],
        latest_account_snapshot: Optional[AccountSnapshot],
        window_start: datetime,
        window_end: datetime,
        now: datetime,
    ) -> ForwardTestReport:
        stats: PerformanceStatistics = self._analytics.compute_performance_statistics(records, now)
        average_rr = _average_rr(records)
        average_slippage, slippage_sample_size = _average_slippage(records)
        missed_trade_count = sum(
            1 for r in records if r.final_outcome is not None and r.final_outcome.rejected_at_stage == "execution_validator"
        )
        blocked_trade_count = sum(
            1 for r in records if r.final_outcome is not None and r.final_outcome.rejected_at_stage == "compliance_engine"
        )

        return ForwardTestReport(
            schema_version=SCHEMA_VERSION,
            generated_at=now,
            window_start=window_start,
            window_end=window_end,
            trade_count=stats.trade_count,
            win_rate=stats.win_rate,
            profit_factor=stats.profit_factor,
            expectancy=stats.expectancy,
            average_rr=average_rr,
            max_drawdown=stats.max_drawdown,
            daily_drawdown_pct=latest_account_snapshot.daily_drawdown_pct if latest_account_snapshot else None,
            total_drawdown_pct=latest_account_snapshot.total_drawdown_pct if latest_account_snapshot else None,
            average_validation_latency_seconds=self._execution_validator_metrics.average_validation_latency_seconds,
            average_broker_latency_seconds=self._mt5_bridge_metrics.average_broker_latency_seconds,
            average_fill_latency_seconds=self._mt5_bridge_metrics.average_fill_latency_seconds,
            average_slippage=average_slippage,
            slippage_sample_size=slippage_sample_size,
            missed_trade_count=missed_trade_count,
            blocked_trade_count=blocked_trade_count,
            duplicate_prevention_count=self._execution_validator_metrics.duplicate_prevention_count,
            recovery_attempt_count=self._watchdog_metrics.restart_count,
            recovery_success_rate=self._watchdog_metrics.recovery_success_rate,
            average_recovery_time_seconds=self._watchdog_metrics.average_recovery_time_seconds,
            analytics_version=stats.analytics_version,
        )


def _average_rr(records: Sequence[TradeProvenanceRecord]) -> Optional[float]:
    """Risk:reward multiple realized per closed trade — `realized_pnl`
    (already recorded on `FinalOutcome`) divided by the risk amount Risk
    Engine already approved (`RiskDecision.approved_risk_amount`) —
    a direct ratio of two already-recorded numbers, never a new estimate."""
    ratios = []
    for record in records:
        if record.final_outcome is None or record.final_outcome.realized_pnl is None:
            continue
        if record.risk_decision is None or not record.risk_decision.approved_risk_amount:
            continue
        ratios.append(record.final_outcome.realized_pnl / record.risk_decision.approved_risk_amount)
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def _average_slippage(records: Sequence[TradeProvenanceRecord]):
    """Fill price minus the market price at the moment closest to
    execution — both already recorded on the same `TradeProvenanceRecord`
    (`market_snapshots`/`fill_reports`). A record missing either is
    skipped, never assumed to have zero slippage."""
    deltas = []
    for record in records:
        if not record.fill_reports or not record.market_snapshots:
            continue
        fill = record.fill_reports[0]
        snapshot = record.market_snapshots[-1]
        deltas.append(abs(fill.fill_price - snapshot.price))
    if not deltas:
        return None, 0
    return sum(deltas) / len(deltas), len(deltas)


__all__ = ["ForwardTestReport", "ForwardTestEngine"]
