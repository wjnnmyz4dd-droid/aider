"""The Validation Dashboard (Phase 4) — read-only.

**Not a modification of `dashboard.models.ViewName`.** That is a closed,
10-value enum Phase 4 has no authorization to extend (`ADR-012` §5's own
exhaustive list) — `ValidationDashboardSnapshot` is a separate,
paper-trading-scoped read type, additive rather than a change to the
existing Dashboard package. Every field is either an already-produced
object passed straight through (`SystemHealth`, `ConnectionStatus`,
`ForwardTestReport`, `PropFirmComplianceStatus`) or a plain filter over
already-collected `TradeProvenanceRecord`s — this module computes nothing
a stage hasn't already computed, and holds no `set_*`/`write_*` method
anywhere, mirroring `dashboard.prometheus_port.PrometheusReadPort`'s own
structural read-only guarantee.

**"Today's trades"/open/closed positions use `SessionManager`'s own
trading-day boundary** (not midnight-UTC-by-coincidence) so a paper
account with a different `daily_reset_hour_utc` sees a dashboard that
agrees with its own `AccountTracker` about what "today" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence, Tuple

from ..analytics import TradeProvenanceRecord
from ..analytics.models import OutcomeKind
from ..mt5_bridge.models import ConnectionStatus
from ..watchdog import SystemHealth
from .forward_test_engine import ForwardTestReport
from .prop_firm_validator import PropFirmComplianceStatus
from .session_manager import SessionManager

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ValidationDashboardSnapshot:
    schema_version: int
    generated_at: datetime

    # "System health" and "Watchdog health" (the task's two separate
    # bullets) are the same already-produced `SystemHealth` object -
    # Watchdog computes this once; nothing here recomputes it a second
    # time under a different name.
    system_health: SystemHealth
    mt5_connection: ConnectionStatus

    todays_trades: Tuple[TradeProvenanceRecord, ...]
    open_positions: Tuple[TradeProvenanceRecord, ...]
    closed_positions: Tuple[TradeProvenanceRecord, ...]

    prop_firm_status: Optional[PropFirmComplianceStatus]
    performance: ForwardTestReport

    def __post_init__(self) -> None:
        object.__setattr__(self, "todays_trades", tuple(self.todays_trades))
        object.__setattr__(self, "open_positions", tuple(self.open_positions))
        object.__setattr__(self, "closed_positions", tuple(self.closed_positions))


class ValidationDashboardBuilder:
    def __init__(self, session_manager: Optional[SessionManager] = None) -> None:
        self._session_manager = session_manager or SessionManager()

    def build(
        self,
        now: datetime,
        system_health: SystemHealth,
        mt5_connection: ConnectionStatus,
        all_records: Sequence[TradeProvenanceRecord],
        performance: ForwardTestReport,
        prop_firm_status: Optional[PropFirmComplianceStatus] = None,
    ) -> ValidationDashboardSnapshot:
        day_start = self._session_manager.trading_day_start(now)
        todays_trades = tuple(r for r in all_records if r.collected_at >= day_start)
        open_positions = tuple(
            r for r in todays_trades if r.final_outcome is not None and r.final_outcome.outcome_kind == OutcomeKind.OPEN
        )
        closed_positions = tuple(
            r for r in todays_trades if r.final_outcome is not None and r.final_outcome.outcome_kind == OutcomeKind.CLOSED
        )
        return ValidationDashboardSnapshot(
            schema_version=SCHEMA_VERSION,
            generated_at=now,
            system_health=system_health,
            mt5_connection=mt5_connection,
            todays_trades=todays_trades,
            open_positions=open_positions,
            closed_positions=closed_positions,
            prop_firm_status=prop_firm_status,
            performance=performance,
        )


__all__ = ["ValidationDashboardSnapshot", "ValidationDashboardBuilder"]
