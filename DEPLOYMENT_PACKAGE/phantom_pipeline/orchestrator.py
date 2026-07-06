"""Pipeline Orchestrator — Phase 2 end-to-end system integration.

**This is not a 13th pipeline stage and introduces no new architecture.**
It is integration glue, exactly like `phantom/api.py` wired the legacy
system together: it holds one already-constructed engine per stage
(constructor injection, mirroring every stage's own pattern) and exposes
only *sequencing* methods that call each stage's existing public API, in
`ADR-001`'s documented order, and forward outputs verbatim. It computes
nothing a stage doesn't already compute, invents no new decision object,
and never skips a stage based on an earlier verdict — each stage's own
fail-closed checks decide that, the same "defense-in-depth, not
duplication" reasoning `ADR-013` §8 already established for Scanner
re-validating Data Pipeline's output.

Order (`ADR-001`, restated by every stage's own "Pipeline position"):
Data Pipeline → Scanner → Strategy Engine → Scoring Engine → Risk Engine
→ Compliance Engine → Execution Validator → MT5 Bridge → Position Manager
→ Analytics, with Watchdog and Dashboard as the cross-cutting observers
`ADR-011`/`ADR-012` define them to be (never a position in the trading
chain).

`CandidateCycleResult`/`ScanCycleResult`/`PositionCycleResult` below are
**not pipeline objects** — nothing downstream consumes them, they carry
no `schema_version`/`trace_id` of their own, and they exist purely as a
local, ergonomic return value for whoever calls the orchestrator (a
driver loop, or a test). Every field inside them is a verbatim reference
to an object a stage already produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Sequence, Tuple, Union

from .analytics.engine import AnalyticsEngine
from .analytics.models import PerformanceStatistics, TradeProvenanceRecord
from .compliance_engine.engine import ComplianceEngine
from .compliance_engine.models import AccountState as ComplianceAccountState
from .compliance_engine.models import ComplianceDecision, NewsCalendarState
from .dashboard.engine import DashboardEngine
from .dashboard.models import AlertView, ComponentStatus, View, ViewName
from .dashboard.prometheus_port import FakePrometheusReadPort
from .data_pipeline.pipeline import DataPipeline
from .execution_validator.engine import ExecutionValidator
from .execution_validator.models import AccountState as ExecutionAccountState
from .execution_validator.models import BrokerState, ExecutionDecision
from .mt5_bridge.engine import MT5Bridge
from .mt5_bridge.models import (
    BrokerError,
    BrokerRequest,
    ConnectionState,
    ExecutionReceipt,
    FillReport,
    PositionAdjustmentRequest,
    PositionCloseRequest,
)
from .position_manager.engine import PositionManager
from .position_manager.models import (
    LifecycleState,
    PositionManagementDecision,
    PositionUpdate,
)
from .risk_engine.engine import RiskEngine
from .risk_engine.models import AccountState as RiskAccountState
from .risk_engine.models import RiskDecision
from .scanner.models import Direction, ScannerObservation
from .scanner.scanner import Scanner
from .scoring_engine.engine import ScoringEngine
from .scoring_engine.models import ScoreResult, ScoringFailureRecord
from .strategy_engine.engine import StrategyEngine
from .strategy_engine.models import CandidateTrade
from .watchdog.engine import WatchdogEngine
from .watchdog.models import ComponentKind, ComponentSignal, HealthState, SystemHealth

BrokerResponse = Union[BrokerRequest, None]
PollResult = Union[ExecutionReceipt, BrokerError, None]

_PIPELINE_STAGE_COMPONENTS = (
    "data_pipeline",
    "scanner",
    "strategy_engine",
    "scoring_engine",
    "risk_engine",
    "compliance_engine",
    "execution_validator",
    "mt5_bridge",
    "position_manager",
    "analytics",
)

# Watchdog "observes and surfaces, never recomputes" MT5 Bridge's own
# connection state machine (ADR-011 Sec5) — a direct field-for-field
# translation, never a re-derivation of what READY/DISCONNECTED means.
_CONNECTION_STATE_TO_HEALTH = {
    ConnectionState.READY: HealthState.HEALTHY,
    ConnectionState.CONNECTED: HealthState.WARNING,
    ConnectionState.SYNCHRONIZING: HealthState.WARNING,
    ConnectionState.CONNECTING: HealthState.WARNING,
    ConnectionState.DISCONNECTED: HealthState.CRITICAL,
}


@dataclass(frozen=True)
class CandidateCycleResult:
    """One `CandidateTrade`'s journey through Scoring → Risk → Compliance
    → Execution Validator → MT5 Bridge, for one `run_scan_cycle` call.
    Not a pipeline object — see module docstring."""

    candidate: CandidateTrade
    score_result: Optional[Union[ScoreResult, ScoringFailureRecord]]
    risk_decision: Optional[RiskDecision]
    compliance_decision: Optional[ComplianceDecision]
    execution_decision: Optional[ExecutionDecision]
    submit_reject_reason: Optional[str]
    broker_request: Optional[BrokerRequest]
    broker_response: BrokerResponse
    poll_result: PollResult


@dataclass(frozen=True)
class ScanCycleResult:
    """One `run_scan_cycle` call's full result — one `ScannerObservation`
    and every candidate it produced, each carried through the rest of the
    chain independently. Not a pipeline object — see module docstring."""

    observation: ScannerObservation
    candidate_results: Tuple[CandidateCycleResult, ...]


@dataclass(frozen=True)
class PositionCycleResult:
    """One `manage_position` call's result. Not a pipeline object."""

    decision: PositionManagementDecision
    update: PositionUpdate
    request: Optional[Union[PositionAdjustmentRequest, PositionCloseRequest]]
    submit_reject_reason: Optional[str]
    broker_request: Optional[BrokerRequest]
    broker_response: BrokerResponse


class PipelineOrchestrator:
    """Holds one already-constructed engine per stage and sequences calls
    across them in `ADR-001`'s documented order. Never constructs a
    stage's collaborators itself (state stores, adapters, registries) —
    those remain the caller's responsibility, exactly as every stage's
    own test suite already does."""

    def __init__(
        self,
        data_pipeline: DataPipeline,
        scanner: Scanner,
        strategy_engine: StrategyEngine,
        scoring_engine: ScoringEngine,
        risk_engine: RiskEngine,
        compliance_engine: ComplianceEngine,
        execution_validator: ExecutionValidator,
        mt5_bridge: MT5Bridge,
        position_manager: PositionManager,
        analytics: AnalyticsEngine,
        watchdog: WatchdogEngine,
        dashboard: DashboardEngine,
        prometheus_port: FakePrometheusReadPort,
    ):
        self.data_pipeline = data_pipeline
        self.scanner = scanner
        self.strategy_engine = strategy_engine
        self.scoring_engine = scoring_engine
        self.risk_engine = risk_engine
        self.compliance_engine = compliance_engine
        self.execution_validator = execution_validator
        self.mt5_bridge = mt5_bridge
        self.position_manager = position_manager
        self.analytics = analytics
        self.watchdog = watchdog
        self.dashboard = dashboard
        self.prometheus_port = prometheus_port

    # -- Data Pipeline -> Scanner -> Strategy -> Scoring -> Risk ->
    # -- Compliance -> Execution Validator -> MT5 Bridge -----------------

    def run_scan_cycle(
        self,
        symbol: str,
        timeframes: Sequence[str],
        primary_timeframe: str,
        session_time: datetime,
        now: datetime,
        risk_account_state: Optional[RiskAccountState],
        compliance_account_state: Optional[ComplianceAccountState],
        execution_account_state: Optional[ExecutionAccountState],
        broker_state: Optional[BrokerState],
        news_state: Optional[NewsCalendarState],
        stop_distance: Optional[float] = None,
        expected_slippage: Optional[float] = None,
        reference_price: Optional[float] = None,
        intended_stop_loss: Optional[float] = None,
        intended_take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> ScanCycleResult:
        """Runs one full trading-pipeline cycle for `symbol`. Every stage
        is always called, regardless of any earlier verdict — a
        `ComplianceDecision` of BLOCK does not stop this method from also
        calling Execution Validator and MT5 Bridge; their own fail-closed
        checks are what reject the trade (never bypassed, never
        duplicated here, `ADR-013` §8's defense-in-depth reasoning)."""

        # Data Pipeline: already-ingested bars/snapshot, read fresh.
        bars_by_timeframe = {
            timeframe: self.data_pipeline.get_historical_series(symbol, timeframe).bars
            for timeframe in timeframes
        }
        market_snapshot = self.data_pipeline.get_snapshot(symbol)
        self.watchdog.record_heartbeat("data_pipeline", now)

        # Scanner
        observation = self.scanner.scan(
            symbol, bars_by_timeframe, market_snapshot, session_time, primary_timeframe
        )
        self.analytics.collect_scanner_observation(observation.trace_id, observation)
        self.watchdog.record_heartbeat("scanner", now)
        self.watchdog.record_heartbeat("analytics", now)

        # Strategy Engine
        candidates = self.strategy_engine.generate(observation, primary_timeframe)
        self.watchdog.record_heartbeat("strategy_engine", now)

        candidate_results = tuple(
            self._run_candidate(
                candidate,
                observation,
                market_snapshot,
                risk_account_state,
                compliance_account_state,
                execution_account_state,
                broker_state,
                news_state,
                now,
                stop_distance,
                expected_slippage,
                reference_price,
                intended_stop_loss,
                intended_take_profit,
                stop_loss,
                take_profit,
            )
            for candidate in candidates
        )

        return ScanCycleResult(observation=observation, candidate_results=candidate_results)

    def _run_candidate(
        self,
        candidate: CandidateTrade,
        observation: ScannerObservation,
        market_snapshot,
        risk_account_state: Optional[RiskAccountState],
        compliance_account_state: Optional[ComplianceAccountState],
        execution_account_state: Optional[ExecutionAccountState],
        broker_state: Optional[BrokerState],
        news_state: Optional[NewsCalendarState],
        now: datetime,
        stop_distance: Optional[float],
        expected_slippage: Optional[float],
        reference_price: Optional[float],
        intended_stop_loss: Optional[float],
        intended_take_profit: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> CandidateCycleResult:
        self.analytics.collect_candidate(candidate.trace_id, candidate)

        # Scoring Engine — a ScoringFailureRecord (malformed/incompatible
        # candidate) is not a ScoreResult and is never forwarded into Risk
        # Engine's strictly-typed input; it is the terminal record for
        # this candidate, already logged/metered inside Scoring Engine
        # itself (ADR-004 §7's "never silently drops," satisfied by it
        # remaining visible on this result, not by inventing a new
        # Analytics collection path for a type Analytics never declared).
        score_or_failure = self.scoring_engine.score(candidate)
        self.watchdog.record_heartbeat("scoring_engine", now)
        if not isinstance(score_or_failure, ScoreResult):
            return CandidateCycleResult(
                candidate=candidate,
                score_result=score_or_failure,
                risk_decision=None,
                compliance_decision=None,
                execution_decision=None,
                submit_reject_reason=None,
                broker_request=None,
                broker_response=None,
                poll_result=None,
            )
        score_result = score_or_failure
        self.analytics.collect_score_result(score_result.trace_id, score_result)

        # Risk Engine
        risk_decision = self.risk_engine.decide(
            score_result, candidate, observation, risk_account_state, stop_distance
        )
        self.analytics.collect_risk_decision(risk_decision.trace_id, risk_decision)
        self.watchdog.record_heartbeat("risk_engine", now)

        # Compliance Engine
        compliance_decision = self.compliance_engine.evaluate(
            risk_decision,
            candidate,
            score_result,
            compliance_account_state,
            market_snapshot,
            news_state,
            expected_slippage,
        )
        self.analytics.collect_compliance_decision(compliance_decision.trace_id, compliance_decision)
        self.watchdog.record_heartbeat("compliance_engine", now)

        # Execution Validator
        execution_decision = self.execution_validator.validate(
            compliance_decision,
            risk_decision,
            score_result,
            candidate,
            market_snapshot,
            broker_state,
            execution_account_state,
            now,
            reference_price,
            intended_stop_loss,
            intended_take_profit,
        )
        self.analytics.collect_execution_decision(execution_decision.trace_id, execution_decision)
        self.watchdog.record_heartbeat("execution_validator", now)

        # MT5 Bridge — always called; its own internal check rejects a
        # non-APPROVE ExecutionDecision (`checks.validate_execution_decision`),
        # never bypassed by this orchestrator.
        submit_reason, broker_request, broker_response = self.mt5_bridge.submit_order(
            execution_decision, risk_decision, compliance_decision, candidate, now, stop_loss, take_profit
        )
        self.watchdog.record_heartbeat("mt5_bridge", now)
        if broker_response is not None:
            self.analytics.collect_broker_event(candidate.trace_id, broker_response)

        poll_result = None
        if broker_request is not None:
            poll_result = self.mt5_bridge.poll_execution(
                broker_request.execution_id, candidate.trace_id, now, now
            )
            if poll_result is not None:
                self.analytics.collect_broker_event(candidate.trace_id, poll_result)

        return CandidateCycleResult(
            candidate=candidate,
            score_result=score_result,
            risk_decision=risk_decision,
            compliance_decision=compliance_decision,
            execution_decision=execution_decision,
            submit_reject_reason=submit_reason,
            broker_request=broker_request,
            broker_response=broker_response,
            poll_result=poll_result,
        )

    # -- Fill callback -> Analytics ---------------------------------------

    def record_fill(self, trace_id: str, fill: FillReport) -> bool:
        """A fill arrives asynchronously, outside `run_scan_cycle`'s own
        request/acknowledge timeline (ADR-008 §5). Forwards to MT5
        Bridge's own duplicate-fill detection, then Analytics — never
        re-derives fill data itself."""
        newly_recorded = self.mt5_bridge.record_fill(fill)
        if newly_recorded:
            self.analytics.collect_fill_report(trace_id, fill)
        self.watchdog.record_heartbeat("mt5_bridge", fill.timestamp)
        return newly_recorded

    # -- Position Manager -> (adjustment/close) -> MT5 Bridge -------------
    # -- (ADR-009 Sec9's one reverse edge) ---------------------------------

    def manage_position(
        self,
        position_id: str,
        trace_id: str,
        direction: Direction,
        entry_price: float,
        lifecycle_state: LifecycleState,
        current_price: Optional[float],
        current_stop_loss: Optional[float],
        current_take_profit: Optional[float],
        opened_at: datetime,
        market_data_timestamp: Optional[datetime],
        broker_position_exists: Optional[bool],
        compliance_kill_switch_active: Optional[bool],
        now: datetime,
        requested_stop_loss: Optional[float] = None,
    ) -> PositionCycleResult:
        decision, update, request = self.position_manager.evaluate(
            position_id=position_id,
            trace_id=trace_id,
            direction=direction,
            entry_price=entry_price,
            lifecycle_state=lifecycle_state,
            current_price=current_price,
            current_stop_loss=current_stop_loss,
            current_take_profit=current_take_profit,
            opened_at=opened_at,
            market_data_timestamp=market_data_timestamp,
            broker_position_exists=broker_position_exists,
            compliance_kill_switch_active=compliance_kill_switch_active,
            now=now,
            requested_stop_loss=requested_stop_loss,
        )
        self.analytics.collect_position_management_decision(trace_id, decision)
        self.analytics.collect_position_update(trace_id, update)
        self.watchdog.record_heartbeat("position_manager", now)

        submit_reason: Optional[str] = None
        broker_request: Optional[BrokerRequest] = None
        broker_response: BrokerResponse = None
        if isinstance(request, PositionAdjustmentRequest):
            submit_reason, broker_request, broker_response = self.mt5_bridge.submit_position_adjustment(
                request, now
            )
        elif isinstance(request, PositionCloseRequest):
            submit_reason, broker_request, broker_response = self.mt5_bridge.submit_position_close(
                request, now
            )
        if broker_response is not None:
            self.analytics.collect_broker_event(trace_id, broker_response)
        if request is not None:
            self.watchdog.record_heartbeat("mt5_bridge", now)

        return PositionCycleResult(
            decision=decision,
            update=update,
            request=request,
            submit_reject_reason=submit_reason,
            broker_request=broker_request,
            broker_response=broker_response,
        )

    # -- Watchdog ----------------------------------------------------------

    def evaluate_watchdog_health(
        self, now: datetime, extra_signals: Sequence[ComponentSignal] = ()
    ) -> SystemHealth:
        """Builds a plain `ComponentSignal` per pipeline stage (Watchdog
        derives HEALTHY/DEGRADED/etc. purely from the heartbeats already
        recorded via `record_heartbeat` throughout this cycle — this
        method never asserts a health verdict itself, per Watchdog's own
        "never fabricate" discipline, ADR-011 Hard Rules) plus whatever
        infrastructure/external-dependency signals the caller supplies.

        `mt5_bridge`'s signal additionally carries `reported_state`,
        translated directly from `MT5Bridge.state` (its own already-
        computed `ConnectionState`) — Watchdog "observes and surfaces,
        never recomputes" that state (ADR-011 Sec5), the same passthrough
        already established for `ADR-008`'s `ConnectionStatus`."""
        signals = tuple(
            ComponentSignal(
                component=name,
                kind=ComponentKind.PIPELINE_STAGE,
                reported_state=(
                    _CONNECTION_STATE_TO_HEALTH.get(self.mt5_bridge.state) if name == "mt5_bridge" else None
                ),
                detail=(f"ConnectionState.{self.mt5_bridge.state.value}" if name == "mt5_bridge" else ""),
            )
            for name in _PIPELINE_STAGE_COMPONENTS
        ) + tuple(extra_signals)
        return self.watchdog.evaluate(signals, now)

    # -- Dashboard (via a Prometheus read port populated from Watchdog) --

    def render_dashboard_snapshot(
        self,
        now: datetime,
        system_health: Optional[SystemHealth] = None,
        records: Sequence[TradeProvenanceRecord] = (),
        performance: Optional[PerformanceStatistics] = None,
    ) -> Dict[str, View]:
        """Translates the latest `SystemHealth` into the Dashboard's own
        `ComponentStatus`/`AlertView` shape via `self.prometheus_port` —
        exactly the field-for-field translation a real Prometheus scrape
        would eventually perform; Dashboard itself still never imports
        Watchdog directly (`ADR-012` §4's structural read-only guarantee
        is unaffected — it only ever reads `self.prometheus_port`)."""
        if system_health is None:
            system_health = self.evaluate_watchdog_health(now)

        for component_health in system_health.component_health:
            self.prometheus_port.set_component_status(
                ComponentStatus(
                    component=component_health.component,
                    health_state=component_health.state.value,
                    reason=component_health.reason,
                    trace_id=system_health.trace_id,
                    timestamp=component_health.timestamp,
                )
            )
        alerts = self.watchdog.generate_alerts(system_health, now)
        self.prometheus_port.set_alerts(
            tuple(
                AlertView(
                    component=alert.component,
                    alert_class=alert.alert_class.value,
                    severity=alert.severity.value,
                    detail=alert.detail,
                    repeat_count=alert.repeat_count,
                    trace_id=alert.trace_id,
                    timestamp=alert.timestamp,
                )
                for alert in alerts
            )
        )

        return {
            ViewName.OVERVIEW.value: self.dashboard.build_overview_view(now, performance=performance),
            ViewName.TRADING.value: self.dashboard.build_trading_view(now, records=records),
            ViewName.RISK.value: self.dashboard.build_risk_view(now, performance=performance),
            ViewName.COMPLIANCE.value: self.dashboard.build_compliance_view(now),
            ViewName.EXECUTION.value: self.dashboard.build_execution_view(now),
            ViewName.INFRASTRUCTURE.value: self.dashboard.build_infrastructure_view(now),
            ViewName.ANALYTICS.value: self.dashboard.build_analytics_view(now, records=records, performance=performance),
            ViewName.ALERTS.value: self.dashboard.build_alerts_view(now),
            ViewName.RESEARCH.value: self.dashboard.build_research_view(now),
            ViewName.AUDIT.value: self.dashboard.build_audit_view(now, records=records),
        }
