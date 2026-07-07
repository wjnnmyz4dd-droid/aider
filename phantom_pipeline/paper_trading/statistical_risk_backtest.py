"""Statistical Risk recommendation backtest (`ADR-022` Amendment 1 §A1.2
item 3).

Compares each closed trade's actual `realized_pnl` against what it would
have been had `StatisticalRiskAssessment.statistical_recommendation`
been followed exactly, using the same reduction fractions
`RiskRecommendation`'s four values already imply (100%/75%/50%/0% of the
approved risk). This is a plain, transparent linear-scaling estimate,
not a full re-simulation: it assumes P/L scales proportionally with
position size, which is the best available signal from already-recorded
data alone — real-world slippage/spread do not scale perfectly linearly,
a known, documented limitation, never hidden or smoothed over. Every
number here is arithmetic over already-recorded fields; nothing is
computed by an LLM or fabricated (`ADR-022` Hard Rule 5, 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, Tuple

from ..analytics.models import OutcomeKind, TradeProvenanceRecord
from ..statistical_risk.models import RiskRecommendation

SCHEMA_VERSION = 1

_RECOMMENDATION_MULTIPLIER = {
    RiskRecommendation.NORMAL_RISK: 1.0,
    RiskRecommendation.REDUCE_RISK_25: 0.75,
    RiskRecommendation.REDUCE_RISK_50: 0.5,
    RiskRecommendation.SKIP_HIGH_RISK: 0.0,
}


@dataclass(frozen=True)
class StatisticalRiskBacktestEntry:
    trace_id: str
    actual_pnl: float
    recommendation: RiskRecommendation
    hypothetical_pnl: float
    pnl_delta: float


@dataclass(frozen=True)
class StatisticalRiskBacktestReport:
    schema_version: int
    generated_at: datetime
    entries: Tuple[StatisticalRiskBacktestEntry, ...]
    actual_total_pnl: float
    hypothetical_total_pnl: float
    improvement: float
    sample_size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


class StatisticalRiskBacktester:
    """Stateless — every call takes its historical input explicitly and
    returns a fresh report, mirroring `StatisticalRiskEngine`'s own
    posture."""

    def evaluate(
        self, records: Sequence[TradeProvenanceRecord], now: datetime
    ) -> StatisticalRiskBacktestReport:
        entries = []
        for record in records:
            assessment = record.statistical_risk_assessment
            outcome = record.final_outcome
            if assessment is None or outcome is None:
                continue
            if outcome.outcome_kind != OutcomeKind.CLOSED or outcome.realized_pnl is None:
                continue
            actual_pnl = outcome.realized_pnl
            multiplier = _RECOMMENDATION_MULTIPLIER[assessment.statistical_recommendation]
            hypothetical_pnl = actual_pnl * multiplier
            entries.append(
                StatisticalRiskBacktestEntry(
                    trace_id=record.trace_id,
                    actual_pnl=actual_pnl,
                    recommendation=assessment.statistical_recommendation,
                    hypothetical_pnl=hypothetical_pnl,
                    pnl_delta=hypothetical_pnl - actual_pnl,
                )
            )

        actual_total_pnl = sum(e.actual_pnl for e in entries)
        hypothetical_total_pnl = sum(e.hypothetical_pnl for e in entries)

        return StatisticalRiskBacktestReport(
            schema_version=SCHEMA_VERSION,
            generated_at=now,
            entries=tuple(entries),
            actual_total_pnl=actual_total_pnl,
            hypothetical_total_pnl=hypothetical_total_pnl,
            improvement=hypothetical_total_pnl - actual_total_pnl,
            sample_size=len(entries),
        )


__all__ = ["StatisticalRiskBacktestEntry", "StatisticalRiskBacktestReport", "StatisticalRiskBacktester"]
