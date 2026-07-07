"""The Paper Trading Runner (Phase 4).

**Executes the existing pipeline exactly as production would — never a
new decision path.** Every trading-relevant method here (`run_scan_cycle`,
`record_fill`, `manage_position`, `evaluate_watchdog_health`,
`render_dashboard_snapshot`) is a thin, same-signature delegation to
`PipelineOrchestrator`'s own already-existing public method (Phase 2) —
this class adds no scoring, risk, compliance, or execution logic of its
own. What it adds is exactly three things Phase 2/3 never needed: a live
tick pull per cycle (via `MarketDataAdapter`), a hard demo-account guard
(via a caller-supplied `confirm_demo_account` callable), and a weekend
skip (via `SessionManager`).

**Never places a live trade — by construction, not by policy alone.**
`BrokerAdapter`'s own ABC (`mt5_bridge.broker_adapter`) has no method
capable of reporting whether a connected account is a demo account —
Phase 3's `MT5Adapter` doesn't expose one either, and this package must
not modify either (out of scope; see `docs/plans/phase4-paper-trading.md`).
`confirm_demo_account` is therefore an injected callable the deployer
wires to their own account-mode check (e.g. `lambda: mt5.account_info().
trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO`) — checked before `connect()`
succeeds, and re-checked before every single cycle-running method, never
trusted from a single check at startup (in case of an account switch
mid-session). If it ever returns `False`, every method below raises
immediately rather than submitting anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Protocol, Sequence

from ..analytics.models import TradeProvenanceRecord
from ..mt5_bridge import BrokerAdapter
from ..orchestrator import PipelineOrchestrator
from ..risk_engine.models import AccountState as RiskAccountState
from ..scanner.models import ScannerObservation
from ..statistical_risk import StatisticalRiskAssessment
from .account_tracker import AccountSnapshot, AccountTracker
from .session_manager import SessionManager


class MarketDataSource(Protocol):
    """Structural type for `data_pipeline.market_data_adapter.
    MarketDataAdapter` (and any equivalent), avoided as a concrete import
    here so this module never reaches into another package's private
    submodule (`scripts/check_architecture.py`'s cross-package rule) —
    `market_data_adapter.py` is not re-exported from `data_pipeline`'s own
    `__init__.py`, by the same "new files only, zero modification"
    boundary Phase 3 established for its own adapters."""

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def poll_ticks(self, pipeline, symbol: str, **kwargs): ...


class PaperTradingRunner:
    def __init__(
        self,
        orchestrator: PipelineOrchestrator,
        mt5_adapter: BrokerAdapter,
        market_data_adapter: MarketDataSource,
        session_manager: SessionManager,
        account_tracker: AccountTracker,
        confirm_demo_account: Callable[[], bool],
    ) -> None:
        self._orchestrator = orchestrator
        self._mt5_adapter = mt5_adapter
        self._market_data_adapter = market_data_adapter
        self._session_manager = session_manager
        self._account_tracker = account_tracker
        self._confirm_demo_account = confirm_demo_account
        self._connected = False

    def _require_demo_account(self) -> None:
        if not self._confirm_demo_account():
            raise RuntimeError(
                "PaperTradingRunner refuses to operate: confirm_demo_account() "
                "did not confirm a demo account. Never places a live trade."
            )

    def connect(self) -> bool:
        self._require_demo_account()
        ok = bool(self._mt5_adapter.connect()) and bool(self._market_data_adapter.connect())
        self._connected = ok
        return ok

    def disconnect(self) -> None:
        self._mt5_adapter.disconnect()
        self._market_data_adapter.disconnect()
        self._connected = False

    def _require_connected(self) -> None:
        self._require_demo_account()
        if not self._connected:
            raise RuntimeError("PaperTradingRunner is not connected; call connect() first")

    def observe_account(self, now: datetime) -> AccountSnapshot:
        """Queries live equity from the demo account and updates
        `AccountTracker`'s running daily/total drawdown computation —
        the same externally-supplied `AccountState.daily_drawdown_pct`/
        `total_drawdown_pct` input `RiskEngine`/`ComplianceEngine` have
        always documented as a caller responsibility (see
        `account_tracker.py`)."""
        self._require_connected()
        equity = self._mt5_adapter.query_account_equity()
        if equity is None:
            raise RuntimeError("no account equity available from MT5Adapter")
        return self._account_tracker.observe(equity, now)

    def is_tradeable_now(self, now: datetime) -> bool:
        """Weekend handling (Session Manager) — a cycle is skipped
        entirely, never submitted with stale/absent weekend data."""
        return self._session_manager.is_trading_day(now)

    def run_scan_cycle(self, symbol: str, timeframes: Sequence[str], primary_timeframe: str, session_time: datetime, now: datetime, *args, **kwargs):
        """Pulls one live tick, then delegates verbatim to
        `PipelineOrchestrator.run_scan_cycle` — identical signature,
        identical behavior, the pipeline's own fail-closed checks decide
        everything downstream exactly as they already do in Phase 2.
        Returns `None` (never submitted) during a weekend/non-trading
        window instead of calling the orchestrator at all."""
        self._require_connected()
        if not self.is_tradeable_now(now):
            return None
        self._market_data_adapter.poll_ticks(self._orchestrator.data_pipeline, symbol)
        return self._orchestrator.run_scan_cycle(symbol, timeframes, primary_timeframe, session_time, now, *args, **kwargs)

    def record_fill(self, trace_id: str, fill) -> bool:
        self._require_connected()
        return self._orchestrator.record_fill(trace_id, fill)

    def manage_position(self, *args, **kwargs):
        self._require_connected()
        return self._orchestrator.manage_position(*args, **kwargs)

    def evaluate_watchdog_health(self, now: datetime, extra_signals=()):
        self._require_connected()
        return self._orchestrator.evaluate_watchdog_health(now, extra_signals)

    def render_dashboard_snapshot(self, now: datetime, **kwargs):
        self._require_connected()
        return self._orchestrator.render_dashboard_snapshot(now, **kwargs)

    def preview_statistical_risk(
        self,
        trace_id: str,
        records: Sequence[TradeProvenanceRecord],
        risk_account_state: Optional[RiskAccountState] = None,
        scanner_observation: Optional[ScannerObservation] = None,
    ) -> Optional[StatisticalRiskAssessment]:
        """Display statistical risk before submitting a simulated trade
        (`ADR-022` Amendment 1 §A1.2 item 3) — read-only, never gates
        `run_scan_cycle`. `None` whenever the orchestrator wasn't
        constructed with a `statistical_risk` engine (advisory feature,
        optional by design). Bars are omitted here deliberately: the
        orchestrator's own per-candidate assessment (computed inside
        `run_scan_cycle`, stored on `CandidateCycleResult.statistical_risk_assessment`)
        already reads the live primary-timeframe bars; this preview is a
        pre-submission, bars-optional convenience read of the same engine."""
        self._require_connected()
        if self._orchestrator.statistical_risk is None:
            return None
        starting_equity = (
            risk_account_state.equity
            if risk_account_state is not None and risk_account_state.equity is not None
            else 0.0
        )
        open_positions = risk_account_state.open_positions if risk_account_state is not None else ()
        return self._orchestrator.statistical_risk.assess(
            trace_id=trace_id,
            records=records,
            starting_equity=starting_equity,
            open_positions=open_positions,
            scanner_observation=scanner_observation,
        )


__all__ = ["PaperTradingRunner"]
