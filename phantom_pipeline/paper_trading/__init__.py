"""Paper Trading & Forward Validation (Phase 4).

**Not a 13th pipeline stage, and no new ADR.** Exactly like
`orchestrator.py` (Phase 2) and the four real adapters (Phase 3), this
package is integration/observability tooling built *around* the
already-Accepted, already-implemented 12-stage pipeline
(`docs/adr/ADR-002` through `ADR-013`) plus its governance layer
(`ADR-014`) — never a new decision authority, never a change to any
existing engine's logic. Every class here either reads already-produced,
immutable pipeline objects, or drives the pipeline's own existing public
methods on a schedule.

See `docs/plans/phase4-paper-trading.md` for the full research/plan
record.
"""

from __future__ import annotations

from .account_tracker import AccountSnapshot, AccountTracker
from .forward_test_engine import ForwardTestEngine, ForwardTestReport
from .paper_trading_runner import MarketDataSource, PaperTradingRunner
from .report_generator import PeriodReport, ReportGenerator
from .prop_firm_validator import (
    FTMO_PROFILE,
    FUNDEDNEXT_PROFILE,
    PropFirmComplianceStatus,
    PropFirmProfile,
    PropFirmValidator,
    RuleFinding,
    RuleStatus,
)
from .validation_dashboard import ValidationDashboardBuilder, ValidationDashboardSnapshot
from .session_manager import (
    DEFAULT_CONFIG as DEFAULT_SESSION_MANAGER_CONFIG,
    Session,
    SessionManager,
    SessionManagerConfig,
    SessionWindow,
)

__all__ = [
    "Session",
    "SessionWindow",
    "SessionManagerConfig",
    "DEFAULT_SESSION_MANAGER_CONFIG",
    "SessionManager",
    "AccountSnapshot",
    "AccountTracker",
    "ForwardTestReport",
    "ForwardTestEngine",
    "RuleStatus",
    "RuleFinding",
    "PropFirmProfile",
    "FTMO_PROFILE",
    "FUNDEDNEXT_PROFILE",
    "PropFirmComplianceStatus",
    "PropFirmValidator",
    "PeriodReport",
    "ReportGenerator",
    "MarketDataSource",
    "PaperTradingRunner",
    "ValidationDashboardSnapshot",
    "ValidationDashboardBuilder",
]
