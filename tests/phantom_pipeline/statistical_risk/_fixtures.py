"""Shared test-only fixtures for the Statistical Risk Management tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from phantom_pipeline.analytics.models import FinalOutcome, OutcomeKind, TradeProvenanceRecord
from phantom_pipeline.data_pipeline.models import DataQuality, NormalizedBar
from phantom_pipeline.risk_engine.models import OpenPosition
from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


def make_closed_record(trace_id: str, realized_pnl: float) -> TradeProvenanceRecord:
    return TradeProvenanceRecord(
        schema_version=1,
        trace_id=trace_id,
        scanner_observation=None,
        candidate=None,
        score_result=None,
        risk_decision=None,
        compliance_decision=None,
        execution_decision=None,
        broker_events=(),
        fill_reports=(),
        position_management_decisions=(),
        position_updates=(),
        position_synchronization_results=(),
        account_snapshots=(),
        market_snapshots=(),
        final_outcome=FinalOutcome(
            outcome_kind=OutcomeKind.CLOSED,
            realized_pnl=realized_pnl,
            mae=None,
            mfe=None,
            close_reason="TIME_EXIT",
            rejected_at_stage=None,
            rejection_reason=None,
        ),
        analytics_version="1.0.0-phase1",
        collected_at=T0,
    )


def make_open_record(trace_id: str) -> TradeProvenanceRecord:
    return TradeProvenanceRecord(
        schema_version=1,
        trace_id=trace_id,
        scanner_observation=None,
        candidate=None,
        score_result=None,
        risk_decision=None,
        compliance_decision=None,
        execution_decision=None,
        broker_events=(),
        fill_reports=(),
        position_management_decisions=(),
        position_updates=(),
        position_synchronization_results=(),
        account_snapshots=(),
        market_snapshots=(),
        final_outcome=FinalOutcome(
            outcome_kind=OutcomeKind.OPEN,
            realized_pnl=None,
            mae=None,
            mfe=None,
            close_reason=None,
            rejected_at_stage=None,
            rejection_reason=None,
        ),
        analytics_version="1.0.0-phase1",
        collected_at=T0,
    )


def make_records(pnls: Sequence[float]) -> Tuple[TradeProvenanceRecord, ...]:
    return tuple(make_closed_record(f"trace-{i}", pnl) for i, pnl in enumerate(pnls))


def make_bars(closes: Sequence[float], symbol: str = "EURUSD") -> Tuple[NormalizedBar, ...]:
    bars = []
    for i, close in enumerate(closes):
        high = close + 0.0010
        low = close - 0.0010
        bars.append(
            NormalizedBar(
                schema_version=1,
                trace_id=f"bar-{i}",
                symbol=symbol,
                timeframe="H1",
                timestamp=T0 + timedelta(hours=i),
                open=close,
                high=high,
                low=low,
                close=close,
                volume=100.0,
                quality=DataQuality.NOMINAL,
                is_repaired=False,
                source="test",
            )
        )
    return tuple(bars)


def make_open_position(
    symbol: str = "EURUSD",
    allocated_risk_percent: float = 1.0,
    correlation_bucket: Optional[str] = "EUR_MAJORS",
) -> OpenPosition:
    return OpenPosition(
        symbol=symbol,
        direction=Direction.UP,
        allocated_risk_percent=allocated_risk_percent,
        correlation_bucket=correlation_bucket,
    )
