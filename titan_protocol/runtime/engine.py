"""Runtime Orchestrator (Phase 3A, ADR-031; cross-pair opportunity
selection barrier, ADR-031 Amendment 1 / ADR-037 + Amendment 1).

`RuntimeOrchestrator` is the ONLY live coordinator. It owns ZERO
trading logic -- every conditional branch below is an equality/
membership check against a value another engine's public interface
already returned, never a threshold, weight, or rule computed inline
(ADR-031 SS2, verified structurally by this package's own architecture
test). It executes Evidence -> Market Intelligence -> Strategy ->
Risk -> Compliance -> Bridge in that fixed order, stopping a pair's
cycle immediately at the first rejection (ADR-031 SS3). Validation
Engine is never imported here -- it never participates in live
execution.

The Opportunity Selection Engine is a component Runtime *consults*
between Strategy and Risk for enabled-window ORB candidates only
(ADR-037 SS5) -- never a seventh pipeline stage Runtime itself performs.
Every pair's front half (Evidence -> Market Intelligence -> Strategy)
still runs exactly once per cycle, unconditionally; only the winning
candidate for an enabled window proceeds into Risk -> Compliance ->
Bridge (ADR-037 SS5.E.4)."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from titan_protocol.bridge.models import ErrorCode, TradeCommand
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import AccountState, ComplianceDecision
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import Bar, EvidenceSnapshot
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot, MarketSafetyInputs, NewsEvent
from titan_protocol.opportunity_selection_engine.engine import OpportunitySelectionEngine
from titan_protocol.opportunity_selection_engine.models import OpportunityCandidate
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import PortfolioState, TradeHistory
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import StrategyId, StrategySnapshot, TradeIntent

from .bridge_handoff import build_trade_command
from .config import RUNTIME_VERSION, RuntimeConfig
from .in_flight_commands import InFlightCommandRegistry
from .logging_sink import log_runtime_audit_record
from .metrics import RuntimeMetrics
from .models import SCHEMA_VERSION, CycleOutcome, CycleReport, CycleStage, RuntimeAuditRecord, StageTiming, TradingProfile

BridgeSubmit = Callable[[TradeCommand, datetime], Optional[ErrorCode]]


def _fingerprint(*values: object) -> str:
    """Deterministic, truncated SHA-256 over already-computed values --
    a checksum, never a new decision computation (Final Release
    Hardening, requirement 4: 'Do not duplicate engine calculations')."""

    return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()[:16]


def _engine_versions() -> Tuple[Tuple[str, str], ...]:
    from titan_protocol.compliance_engine.config import COMPLIANCE_ENGINE_VERSION
    from titan_protocol.evidence_engine.config import EVIDENCE_ENGINE_VERSION
    from titan_protocol.market_intelligence.config import MARKET_INTELLIGENCE_ENGINE_VERSION
    from titan_protocol.risk_engine.config import RISK_ENGINE_VERSION
    from titan_protocol.strategy_engine.config import STRATEGY_ENGINE_VERSION

    return (
        ("evidence_engine", EVIDENCE_ENGINE_VERSION),
        ("market_intelligence", MARKET_INTELLIGENCE_ENGINE_VERSION),
        ("strategy_engine", STRATEGY_ENGINE_VERSION),
        ("risk_engine", RISK_ENGINE_VERSION),
        ("compliance_engine", COMPLIANCE_ENGINE_VERSION),
        ("runtime", RUNTIME_VERSION),
    )


_ENGINE_VERSIONS = _engine_versions()
_logger = logging.getLogger("titan_protocol.runtime.engine")


@dataclass
class _FrontHalfResult:
    """Module-private: the shared, already-computed front-half state
    `run_cycle()`'s per-window resolution code (and `_run_back_half`)
    need, without re-deriving anything. `stage_timings` is the same
    mutable list `_run_back_half` continues to append RISK/COMPLIANCE/
    BRIDGE timings to -- identical accumulator, not a fresh one.

    `pair` is `_run_front_half`'s own caller-supplied parameter, carried
    through verbatim -- deliberately never `strategy.pair` (a real
    `StrategyEngine` always echoes the same pair it was asked about, but
    a test double is not guaranteed to; the pre-existing monolithic
    function's own audit record always used the caller-supplied `pair`,
    independent of anything the Strategy Engine returns, and this field
    exists solely to preserve that exact, already-tested invariant
    byte-for-byte -- see `tests/titan_protocol/e2e/test_recovery.py`'s
    `TestLostHeartbeat`, which depends on it directly)."""

    pair: str
    evidence: EvidenceSnapshot
    market_intelligence: MarketIntelligenceSnapshot
    strategy: StrategySnapshot
    evidence_id: str
    stage_timings: List[StageTiming]
    started_at: datetime


class RuntimeOrchestrator:
    def __init__(
        self,
        config: RuntimeConfig,
        evidence_engine: EvidenceEngine,
        market_intelligence_engine: MarketIntelligenceEngine,
        strategy_engine: StrategyEngine,
        risk_engine: RiskEngine,
        compliance_engine: ComplianceEngine,
        bridge_submit: Optional[BridgeSubmit] = None,
        metrics: Optional[RuntimeMetrics] = None,
        timeframe: str = "",
        in_flight_commands: Optional[InFlightCommandRegistry] = None,
        opportunity_selection_engine: Optional[OpportunitySelectionEngine] = None,
    ) -> None:
        self.config = config
        self.evidence_engine = evidence_engine
        self.market_intelligence_engine = market_intelligence_engine
        self.strategy_engine = strategy_engine
        self.risk_engine = risk_engine
        self.compliance_engine = compliance_engine
        self.bridge_submit = bridge_submit
        self.metrics = metrics
        # Final Release Hardening -- recorded on every RuntimeAuditRecord
        # (requirement 4: "symbol and timeframe"). A plain label, not the
        # market_data_ingestion.Timeframe enum -- Runtime does not import
        # that pipeline-stage package for a label alone.
        self.timeframe = timeframe
        # Pair-level in-flight command guard (fixes: this orchestrator
        # previously had no memory of a command it already submitted for
        # a pair, so it would submit a fresh one every cycle with a new
        # correlation_id for as long as compliance kept approving --
        # see titan_protocol/runtime/in_flight_commands.py). Optional and
        # defaulting to None so every existing caller/test that
        # constructs this class without it is unaffected (old behavior:
        # no gate at all).
        self.in_flight_commands = in_flight_commands
        # Cross-pair ORB opportunity-selection consultation (ADR-037 +
        # Amendment 1, ADR-031 Amendment 1). Optional and defaulting to
        # None, mirroring `bridge_submit`/`in_flight_commands`'s own
        # established additive-collaborator pattern -- every existing
        # caller/test that constructs this class without it is
        # unaffected. `run_cycle()`'s own barrier logic (below) never
        # dereferences this attribute unless an enabled window actually
        # produces a barrier participant, which cannot happen while no
        # caller ever configures a non-empty `enabled_windows` list.
        self.opportunity_selection_engine = opportunity_selection_engine

    def _build_audit_record(
        self,
        cycle_id: str,
        pair: str,
        profile: TradingProfile,
        started_at: datetime,
        now: datetime,
        stage_timings: List[StageTiming],
        outcome: CycleOutcome,
        stage_reached: Optional[CycleStage],
        evidence_id: Optional[str] = None,
        selected_strategy: Optional[StrategyId] = None,
        trade_intent: TradeIntent = TradeIntent.NONE,
        risk_approved: Optional[bool] = None,
        compliance_decision: Optional[ComplianceDecision] = None,
        bridge_error: Optional[ErrorCode] = None,
        reasons: Tuple[str, ...] = (),
        evidence=None,
        market_intelligence=None,
        risk=None,
        compliance=None,
        bridge_correlation_id: Optional[str] = None,
    ) -> RuntimeAuditRecord:
        """A plain instance method -- not a nested closure -- so it is
        reachable both from `_run_front_half`/`_run_back_half`'s own
        early-exit returns and from `run_cycle()`'s own aggregate
        per-window termination code, which runs after every pair's
        front/back-half calls have already returned (a closure defined
        inside one of those calls cannot be invoked once its enclosing
        call has returned). Every parameter below is an already-computed
        value the caller already holds; nothing here evaluates new
        decision logic, only extraction and hashing (Final Release
        Hardening, requirement 4)."""
        ended_at = now
        duration_ms = sum(t.duration_ms for t in stage_timings)

        evidence_summary = evidence.report.confidence_explanation if evidence is not None else ""
        market_intelligence_summary = (
            market_intelligence.explanation.trade_readiness_explanation if market_intelligence is not None else ""
        )
        risk_reasons = risk.reasons if risk is not None else ()
        compliance_triggered_rules = (
            tuple(rule.value for rule in compliance.triggered_rules) if compliance is not None else ()
        )
        lock_recommendation = compliance.lock_recommendation if compliance is not None else None
        compliance_lock_trigger = lock_recommendation.trigger if lock_recommendation is not None else None
        compliance_lock_reason = lock_recommendation.reason if lock_recommendation is not None else None
        decision_id = f"{cycle_id}:{pair}"
        snapshot_hash = _fingerprint(pair, profile.profile_id, profile.version, SCHEMA_VERSION, evidence_id, self.timeframe)
        decision_fingerprint = _fingerprint(
            outcome.value, stage_reached.value if stage_reached is not None else None,
            selected_strategy, trade_intent.value,
            risk_approved, compliance_decision.value if compliance_decision is not None else None, reasons,
        )

        record = RuntimeAuditRecord(
            cycle_id=cycle_id, pair=pair, profile_id=profile.profile_id,
            configuration_version=profile.version, started_at=started_at, ended_at=ended_at,
            duration_ms=duration_ms, outcome=outcome, stage_reached=stage_reached,
            evidence_id=evidence_id, selected_strategy=selected_strategy, trade_intent=trade_intent,
            risk_approved=risk_approved, compliance_decision=compliance_decision, bridge_error=bridge_error,
            reasons=reasons, stage_timings=tuple(stage_timings), engine_versions=_ENGINE_VERSIONS,
            decision_id=decision_id, config_schema_version=SCHEMA_VERSION, timeframe=self.timeframe,
            evidence_summary=evidence_summary, market_intelligence_summary=market_intelligence_summary,
            risk_reasons=risk_reasons, compliance_triggered_rules=compliance_triggered_rules,
            compliance_lock_trigger=compliance_lock_trigger, compliance_lock_reason=compliance_lock_reason,
            bridge_correlation_id=bridge_correlation_id, snapshot_hash=snapshot_hash,
            decision_fingerprint=decision_fingerprint,
        )
        log_runtime_audit_record(record)
        return record

    def _run_front_half(
        self,
        pair: str,
        bars: Sequence[Bar],
        events: Sequence[NewsEvent],
        current_spread: float,
        average_spread: float,
        market_safety_inputs: MarketSafetyInputs,
        profile: TradingProfile,
        now: datetime,
        cycle_id: str,
    ) -> Tuple[bool, Union[RuntimeAuditRecord, _FrontHalfResult]]:
        """Everything from today's cycle start through the
        `strategy.rejected` check. Returns `(strategy_completed, result)`.

        `strategy_completed` is set to `True` at exactly one place --
        immediately after `self.strategy_engine.evaluate(...)` **returns
        successfully**, before any inspection of `strategy.rejected` or
        any other field. It is never derived from, or inferred by
        pattern-matching on, which `CycleOutcome`/`stage_reached` a
        terminal record happens to carry: `last_stage` is set to
        `CycleStage.STRATEGY` immediately *before* the Strategy call
        executes, so an exception raised by the call itself still
        carries `stage_reached=CycleStage.STRATEGY` on its `FAILED`
        record, yet must **not** count as terminal -- only this boolean,
        set strictly *after* the call returns, distinguishes the two."""
        started_at = now
        stage_timings: List[StageTiming] = []
        last_stage: Optional[CycleStage] = None

        try:
            if not profile.trading_window.contains(now):
                return False, self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.OUTSIDE_TRADING_WINDOW, None, reasons=("outside configured trading window",),
                )

            last_stage = CycleStage.EVIDENCE
            stage_start = time.monotonic()
            evidence = self.evidence_engine.evaluate_snapshot(pair, bars, now)
            stage_timings.append(StageTiming(CycleStage.EVIDENCE, (time.monotonic() - stage_start) * 1000.0))
            evidence_id = f"{pair}:{evidence.report.generated_at.isoformat()}"

            if profile.session_rules and evidence.session.session not in profile.session_rules:
                return False, self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.SESSION_NOT_ALLOWED, CycleStage.EVIDENCE, evidence_id=evidence_id,
                    reasons=(f"session {evidence.session.session.value} not in this profile's session_rules",),
                    evidence=evidence,
                )

            last_stage = CycleStage.MARKET_INTELLIGENCE
            stage_start = time.monotonic()
            market_intelligence = self.market_intelligence_engine.evaluate(
                pair, evidence.report, events, current_spread, average_spread, market_safety_inputs, now,
            )
            stage_timings.append(StageTiming(CycleStage.MARKET_INTELLIGENCE, (time.monotonic() - stage_start) * 1000.0))

            last_stage = CycleStage.STRATEGY
            stage_start = time.monotonic()
            strategy = self.strategy_engine.evaluate(pair, evidence, market_intelligence, now)
            stage_timings.append(StageTiming(CycleStage.STRATEGY, (time.monotonic() - stage_start) * 1000.0))
            strategy_completed = True

            if strategy.rejected:
                return strategy_completed, self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.NO_STRATEGY, CycleStage.STRATEGY, evidence_id=evidence_id,
                    reasons=(strategy.rejection_reason or "no strategy qualified",),
                    evidence=evidence, market_intelligence=market_intelligence,
                )

            return strategy_completed, _FrontHalfResult(
                pair=pair, evidence=evidence, market_intelligence=market_intelligence, strategy=strategy,
                evidence_id=evidence_id, stage_timings=stage_timings, started_at=started_at,
            )
        except Exception as exc:  # noqa: BLE001 -- fail closed, never propagate a partial cycle
            if self.metrics is not None:
                self.metrics.record_failure()
            return False, self._build_audit_record(
                cycle_id, pair, profile, started_at, now, stage_timings,
                CycleOutcome.FAILED, last_stage, reasons=(repr(exc),),
            )

    def _run_back_half(
        self,
        front_half: _FrontHalfResult,
        portfolio_state: PortfolioState,
        trade_history: Optional[TradeHistory],
        account_state: AccountState,
        profile: TradingProfile,
        now: datetime,
        cycle_id: str,
    ) -> RuntimeAuditRecord:
        """Everything from today's `last_stage = CycleStage.RISK`
        onward (Risk -> Compliance -> Bridge, unchanged verbatim), taking
        a `_FrontHalfResult` instead of re-deriving anything. `pair` comes
        from `front_half.pair` (the original caller-supplied value, not
        `front_half.strategy.pair`) -- preserves the pre-existing
        monolithic function's exact behavior of using its own `pair`
        parameter for the audit record, independent of whatever the
        Strategy Engine's own snapshot reports."""
        pair = front_half.pair
        evidence = front_half.evidence
        market_intelligence = front_half.market_intelligence
        strategy = front_half.strategy
        evidence_id = front_half.evidence_id
        stage_timings = front_half.stage_timings
        started_at = front_half.started_at

        last_stage: Optional[CycleStage] = CycleStage.STRATEGY
        risk = None
        reservation_owned_by_registry = False

        try:
            last_stage = CycleStage.RISK
            stage_start = time.monotonic()
            risk = self.risk_engine.evaluate(pair, evidence, market_intelligence, strategy, portfolio_state, trade_history, now)
            stage_timings.append(StageTiming(CycleStage.RISK, (time.monotonic() - stage_start) * 1000.0))

            if not risk.approved:
                return self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.RISK_REJECTED, CycleStage.RISK, evidence_id=evidence_id,
                    selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                    risk_approved=False,
                    reasons=risk.reasons or (risk.rejection_reason.value if risk.rejection_reason else "rejected",),
                    evidence=evidence, market_intelligence=market_intelligence, risk=risk,
                )

            last_stage = CycleStage.COMPLIANCE
            stage_start = time.monotonic()
            compliance = self.compliance_engine.evaluate(
                pair, evidence, market_intelligence, strategy, risk, portfolio_state, account_state, now,
            )
            stage_timings.append(StageTiming(CycleStage.COMPLIANCE, (time.monotonic() - stage_start) * 1000.0))

            if compliance.decision is ComplianceDecision.REJECT:
                # Risk Engine reserved this candidate's risk_r before
                # Compliance ever ran (ReservationLedger.reserve_if(),
                # ADR-027 Hard Rule 5); Compliance's rejection means no
                # command will ever be built for it, so its reservation
                # must be released here -- otherwise it leaks
                # permanently (the exact defect this release call
                # closes; see risk_engine/reservation.py). Compliance
                # never touches Risk Engine's reservation_id itself
                # (ADR-028 Hard Rule 6: ComplianceEngine holds no
                # mutable state and no dependency on risk_engine's
                # internals) -- release ownership belongs to Runtime,
                # the only caller that holds both engines.
                if risk.reservation_id is not None:
                    self.risk_engine.release_reservation(risk.reservation_id)
                return self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.COMPLIANCE_REJECTED, CycleStage.COMPLIANCE, evidence_id=evidence_id,
                    selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                    risk_approved=True, compliance_decision=compliance.decision, reasons=(compliance.reason,),
                    evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                )

            last_stage = CycleStage.BRIDGE
            stage_start = time.monotonic()
            bridge_error: Optional[ErrorCode] = None
            command = None
            in_flight_blocked = (
                self.in_flight_commands is not None and self.in_flight_commands.has_unresolved(pair, now)
            )
            awaiting_position_confirmation = (
                self.in_flight_commands is not None and self.in_flight_commands.is_awaiting_position_confirmation(pair)
            )
            if in_flight_blocked:
                # Risk/Compliance already ran and reserved this cycle's
                # candidate risk_r before this in-flight check -- a
                # previously-submitted command for this pair is still
                # unresolved, so this cycle's decision is discarded
                # without ever reaching the Bridge. Without this
                # release, a blocked pair would re-reserve every single
                # cycle it stays blocked (not once per real trade) --
                # the single largest contributor to the reservation leak
                # this release call closes.
                if risk.reservation_id is not None:
                    self.risk_engine.release_reservation(risk.reservation_id)
                _logger.info(
                    "in_flight_command_pending",
                    extra={
                        "pair": pair,
                        "correlation_id": self.in_flight_commands.correlation_id_for(pair),
                        "in_flight_count": self.in_flight_commands.in_flight_count(),
                        "awaiting_position_confirmation": awaiting_position_confirmation,
                    },
                )
            elif self.bridge_submit is not None and compliance.ready_for_bridge:
                command = build_trade_command(pair, strategy, risk, compliance, cycle_id, now, self.config)
                bridge_error = self.bridge_submit(command, now)
                if bridge_error is None:
                    # Ownership handoff: from this point on the
                    # reservation belongs to InFlightCommandRegistry, not
                    # to this local `risk` snapshot -- it is released
                    # from there (execution rejection, abandonment, TTL
                    # expiry) or, for a genuine success, only once
                    # confirm_position_report() proves real exposure
                    # exists. If in_flight_commands is None (not wired,
                    # e.g. some tests), there is no persistent lifecycle
                    # object to hand off to -- release immediately rather
                    # than leak, since nothing will ever track it.
                    if self.in_flight_commands is not None:
                        self.in_flight_commands.record_submission(
                            pair, command.correlation_id, now, reservation_id=risk.reservation_id,
                        )
                        reservation_owned_by_registry = True
                    elif risk.reservation_id is not None:
                        self.risk_engine.release_reservation(risk.reservation_id)
            else:
                # Neither branch above ran: either no bridge_submit is
                # wired at all, or compliance.ready_for_bridge is False
                # (reachable when a REDUCE decision's graduated sizing
                # floors approved_size_r to zero -- see
                # ComplianceSnapshot.ready_for_bridge). Either way no
                # command will ever be built for this cycle's
                # reservation -- release it here rather than let it
                # leak silently.
                if risk.reservation_id is not None:
                    self.risk_engine.release_reservation(risk.reservation_id)
            stage_timings.append(StageTiming(CycleStage.BRIDGE, (time.monotonic() - stage_start) * 1000.0))
            bridge_correlation_id = command.correlation_id if command is not None else None

            if in_flight_blocked:
                reason = (
                    "a command for this pair resolved but a fresh post-execution position report "
                    "has not yet been observed" if awaiting_position_confirmation
                    else "an unresolved command already exists for this pair"
                )
                return self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.IN_FLIGHT_COMMAND_PENDING, CycleStage.BRIDGE, evidence_id=evidence_id,
                    selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                    risk_approved=True, compliance_decision=compliance.decision,
                    reasons=(reason,),
                    evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                    bridge_correlation_id=self.in_flight_commands.correlation_id_for(pair),
                )

            if bridge_error is not None:
                # Command was built (compliance approved, ready_for_bridge
                # was True) but Bridge/CommandQueue itself rejected it
                # (validation.py's transport-integrity checks, or
                # CommandQueue.enqueue() refusing while not is_ready) --
                # record_submission() is only ever called when
                # bridge_error is None (see the elif branch above), so
                # ownership never transferred to InFlightCommandRegistry
                # here; release unconditionally.
                if risk.reservation_id is not None:
                    self.risk_engine.release_reservation(risk.reservation_id)
                return self._build_audit_record(
                    cycle_id, pair, profile, started_at, now, stage_timings,
                    CycleOutcome.BRIDGE_ERROR, CycleStage.BRIDGE, evidence_id=evidence_id,
                    selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                    risk_approved=True, compliance_decision=compliance.decision, bridge_error=bridge_error,
                    reasons=(bridge_error.value,),
                    evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                    bridge_correlation_id=bridge_correlation_id,
                )

            return self._build_audit_record(
                cycle_id, pair, profile, started_at, now, stage_timings,
                CycleOutcome.SUBMITTED, CycleStage.BRIDGE, evidence_id=evidence_id,
                selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                risk_approved=True, compliance_decision=compliance.decision, reasons=(compliance.reason,),
                evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                bridge_correlation_id=bridge_correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 -- fail closed, never propagate a partial cycle
            # Guaranteed cleanup path (no orphan window between
            # reservation creation and ownership handoff): if Risk
            # Engine already reserved this candidate's risk_r (`risk` is
            # bound and carries a reservation_id) but the cycle failed
            # before that ownership ever transferred to
            # InFlightCommandRegistry (`reservation_owned_by_registry`
            # still False), release it here -- otherwise an exception
            # anywhere between Risk Engine's evaluate() and the handoff
            # point (Compliance, command construction, bridge_submit,
            # or `_build_audit_record()`/logging itself) would leak the
            # reservation exactly like the defect this whole change
            # closes.
            if risk is not None and risk.reservation_id is not None and not reservation_owned_by_registry:
                self.risk_engine.release_reservation(risk.reservation_id)
            if self.metrics is not None:
                self.metrics.record_failure()
            return self._build_audit_record(
                cycle_id, pair, profile, started_at, now, stage_timings,
                CycleOutcome.FAILED, last_stage, reasons=(repr(exc),),
            )

    def run_cycle_for_pair(
        self,
        pair: str,
        bars: Sequence[Bar],
        events: Sequence[NewsEvent],
        current_spread: float,
        average_spread: float,
        market_safety_inputs: MarketSafetyInputs,
        portfolio_state: PortfolioState,
        trade_history: Optional[TradeHistory],
        account_state: AccountState,
        profile: TradingProfile,
        now: datetime,
        cycle_id: str,
    ) -> RuntimeAuditRecord:
        """Byte-for-byte identical observable behavior to the pre-ADR-037
        monolithic function for every existing caller/test: call
        `_run_front_half`; if it returned a terminal record, return it;
        otherwise immediately call `_run_back_half` with the
        `_FrontHalfResult` and return that. Discards the `strategy_
        completed` boolean, which only `run_cycle()`'s own new
        sequencing needs."""
        try:
            _strategy_completed, front_result = self._run_front_half(
                pair, bars, events, current_spread, average_spread, market_safety_inputs, profile, now, cycle_id,
            )
            if isinstance(front_result, RuntimeAuditRecord):
                return front_result
            return self._run_back_half(front_result, portfolio_state, trade_history, account_state, profile, now, cycle_id)
        finally:
            if self.metrics is not None:
                self.metrics.record_cycle()

    def run_cycle(
        self,
        pairs: Sequence[str],
        profile: TradingProfile,
        inputs: Dict[str, Tuple[
            Sequence[Bar], Sequence[NewsEvent], float, float, MarketSafetyInputs,
            PortfolioState, Optional[TradeHistory], AccountState,
        ]],
        now: datetime,
        cycle_id: str,
    ) -> CycleReport:
        """`inputs[pair]` supplies every per-pair raw value
        `run_cycle_for_pair` needs, as a tuple in the same order as its
        keyword-free positional arguments (bars, events, current_spread,
        average_spread, market_safety_inputs, portfolio_state,
        trade_history, account_state). Only pairs in
        `profile.allowed_pairs` are evaluated -- others are skipped
        before any engine is called.

        Cross-pair ORB opportunity selection (ADR-037 + Amendment 1):
        every pair's front half runs exactly once, unconditionally
        (ADR-037 SS5.A). A pair whose result is an enabled-window ORB
        candidate waits at a barrier until every tracked pair has
        reached a terminal front-half outcome (or the scan is judged
        incomplete); every other pair proceeds immediately, exactly as
        today. Only the winner (if any) for each enabled window
        proceeds into Risk -> Compliance -> Bridge; every other barrier
        participant terminates with `NOT_SELECTED_OPPORTUNITY_WINDOW`."""

        started_at = now
        records: List[RuntimeAuditRecord] = []

        # Step 1: freeze the tracking universe once, at cycle start
        # (ADR-037 SS7 / ADR-031 Amendment 1 SS2's frozen `Gate A ∩
        # allowed_pairs` completeness-tracking subset -- never the
        # complete set of pairs evaluated; every pair in
        # `profile.allowed_pairs` still gets its front half regardless
        # of `tracked_pairs` membership). Computed only when an
        # Opportunity Selection Engine is actually wired in -- `run_cycle()`
        # predates ADR-037 (it already existed as a plain per-pair
        # `run_cycle_for_pair()` loop, with its own existing direct
        # callers/tests, e.g. `tests/titan_protocol/e2e/test_recovery.py`,
        # whose strategy-engine stubs have no `.config` attribute at all).
        # Referencing `self.strategy_engine.config` unconditionally would
        # regress every one of those callers for no reason: tracked_pairs
        # is meaningless without an engine to consult anyway (no windows,
        # no barrier possible).
        tracked_pairs: set = set()
        if self.opportunity_selection_engine is not None:
            tracked_pairs = set(
                self.strategy_engine.config.approved_pairs_for(StrategyId.OPENING_RANGE_BREAKOUT)
            ) & set(profile.allowed_pairs)
        reached_terminal: Dict[str, bool] = {}

        # Enabled windows' concrete range_start values for this cycle,
        # keyed by that range_start (a plain timestamp-label construction
        # against the same anchor hour/minute a configured window
        # references -- never a re-derivation of ORB's own "currently
        # relevant range" logic, which remains solely `orb_breakout.py`'s
        # own authority).
        enabled_range_starts: Dict[datetime, "EnabledOpportunityWindow"] = {}
        if self.opportunity_selection_engine is not None:
            for window in self.opportunity_selection_engine.config.enabled_windows:
                if not window.enabled:
                    continue
                window_range_start = now.replace(
                    hour=window.anchor_hour_utc, minute=window.anchor_minute_utc, second=0, microsecond=0,
                )
                enabled_range_starts[window_range_start] = window

        # Per-window pending state: range_start -> list of
        # (pair, _FrontHalfResult, portfolio_state, trade_history, account_state)
        # tuples awaiting that window's completeness/selection resolution.
        pending_by_window: Dict[datetime, list] = {rs: [] for rs in enabled_range_starts}

        for pair in sorted(pairs):
            if pair not in profile.allowed_pairs:
                continue
            (bars, events, current_spread, average_spread, market_safety_inputs,
             portfolio_state, trade_history, account_state) = inputs[pair]

            strategy_completed, result = self._run_front_half(
                pair, bars, events, current_spread, average_spread, market_safety_inputs, profile, now, cycle_id,
            )
            if self.metrics is not None:
                self.metrics.record_cycle()
            if pair in tracked_pairs:
                reached_terminal[pair] = strategy_completed

            if isinstance(result, RuntimeAuditRecord):
                # A terminal front-half outcome (OUTSIDE_TRADING_WINDOW,
                # SESSION_NOT_ALLOWED, NO_STRATEGY, or a pre-Strategy
                # FAILED) -- `reached_terminal[pair]` was already
                # correctly set above, independent of which of these
                # four it is.
                records.append(result)
                continue

            # `result` is a `_FrontHalfResult`. Classify using only
            # already-computed fields (ADR-037 SS5.B): `strategy.
            # rejected` was already `False` (routed to the terminal-
            # record branch above otherwise), so `winning_strategy` is
            # never `None` here.
            winning_strategy = result.strategy.winning_strategy
            window = None
            if winning_strategy.strategy_id is StrategyId.OPENING_RANGE_BREAKOUT:
                candidate_range_start = winning_strategy.qualification.range_start
                # Invariant, verified directly against `orb_breakout.py`'s
                # own control flow: `winning_strategy.strategy_id is
                # OPENING_RANGE_BREAKOUT` implies `qualification.range_
                # start is not None` -- every `NOT_QUALIFIED` return in
                # `qualify()` precedes the line that sets `range_start`
                # on the `QUALIFIED` result. If this invariant is ever
                # violated, fail closed rather than treat it as an
                # ordinary path: never a barrier participant.
                if candidate_range_start is not None:
                    window = enabled_range_starts.get(candidate_range_start)

            if window is None:
                # Non-participating: a legacy-strategy winner, an ORB
                # result whose range belongs to a non-enabled or
                # unconfigured window, or no formed range at all.
                # Proceeds immediately, unmodified -- no waiting, no
                # added latency.
                records.append(self._run_back_half(result, portfolio_state, trade_history, account_state, profile, now, cycle_id))
            else:
                # Barrier participant: hold for this window's
                # completeness/selection resolution below.
                pending_by_window[candidate_range_start].append(
                    (pair, result, portfolio_state, trade_history, account_state)
                )

        # Step 3: after every pair's front half has run exactly once
        # (never once per window), resolve each enabled window.
        incomplete = any(pair not in reached_terminal or not reached_terminal[pair] for pair in tracked_pairs)

        for window_range_start, window in enabled_range_starts.items():
            pending = pending_by_window[window_range_start]

            _log_pending_candidates(window_range_start, window.session_name, len(pending))

            if incomplete:
                # ADR-037 SS5.E.2: never passed to the engine at all --
                # this window's barrier fails closed directly.
                for pair, front_result, *_ in pending:
                    if self.metrics is not None:
                        self.metrics.record_cycle()
                    records.append(self._build_audit_record(
                        cycle_id, pair, profile, front_result.started_at, now, front_result.stage_timings,
                        CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW, CycleStage.STRATEGY,
                        evidence_id=front_result.evidence_id,
                        selected_strategy=StrategyId.OPENING_RANGE_BREAKOUT,
                        trade_intent=front_result.strategy.trade_intent,
                        reasons=("opportunity window scan incomplete this cycle",),
                        evidence=front_result.evidence, market_intelligence=front_result.market_intelligence,
                    ))
                continue

            try:
                candidates = tuple(
                    OpportunityCandidate(
                        pair=pair,
                        score=front_result.strategy.winning_strategy.qualification.score,
                        trade_intent=front_result.strategy.trade_intent,
                    )
                    for pair, front_result, *_ in pending
                )
                outcome = self.opportunity_selection_engine.evaluate_window(
                    window_range_start, window.session_name, candidates, now,
                )
            except Exception as exc:  # noqa: BLE001 -- the engine's own call, candidate construction, or store.decide_once()
                if self.opportunity_selection_engine is not None and self.opportunity_selection_engine.metrics is not None:
                    self.opportunity_selection_engine.metrics.record_selector_failure()
                _log_opportunity_selection_failure(window_range_start, window.session_name, exc)
                for pair, front_result, *_ in pending:
                    if self.metrics is not None:
                        self.metrics.record_cycle()
                    records.append(self._build_audit_record(
                        cycle_id, pair, profile, front_result.started_at, now, front_result.stage_timings,
                        CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW, CycleStage.STRATEGY,
                        evidence_id=front_result.evidence_id,
                        selected_strategy=StrategyId.OPENING_RANGE_BREAKOUT,
                        trade_intent=front_result.strategy.trade_intent,
                        reasons=("opportunity selection failed for this window",),
                        evidence=front_result.evidence, market_intelligence=front_result.market_intelligence,
                    ))
                continue

            for pair, front_result, portfolio_state, trade_history, account_state in pending:
                if outcome.winner is not None and pair == outcome.winner:
                    records.append(self._run_back_half(
                        front_result, portfolio_state, trade_history, account_state, profile, now, cycle_id,
                    ))
                else:
                    if self.metrics is not None:
                        self.metrics.record_cycle()
                    reason = (
                        "another candidate was selected for this opportunity window" if outcome.winner is not None
                        else "no candidate selected for this opportunity window (tie or no qualifying candidate)"
                    )
                    records.append(self._build_audit_record(
                        cycle_id, pair, profile, front_result.started_at, now, front_result.stage_timings,
                        CycleOutcome.NOT_SELECTED_OPPORTUNITY_WINDOW, CycleStage.STRATEGY,
                        evidence_id=front_result.evidence_id,
                        selected_strategy=StrategyId.OPENING_RANGE_BREAKOUT,
                        trade_intent=front_result.strategy.trade_intent,
                        reasons=(reason,),
                        evidence=front_result.evidence, market_intelligence=front_result.market_intelligence,
                    ))

        ended_at = now  # same single caller-supplied clock reading, never a fresh wall-clock read (determinism)
        total_duration_ms = sum(r.duration_ms for r in records)
        return CycleReport(cycle_id=cycle_id, started_at=started_at, ended_at=ended_at, duration_ms=total_duration_ms, records=tuple(records))


def _log_pending_candidates(range_start: datetime, session_name, pending_count: int) -> None:
    """Runtime-side "window scan started with N pending candidates" log
    line, emitted once per enabled window immediately before that
    window's completeness/selection resolution (ADR-031 Amendment 1 SS7
    item 1's barrier-pending observability signal)."""
    try:
        _logger.info(
            "opportunity_window_scan_started",
            extra={"range_start": range_start.isoformat(), "session_name": session_name.value, "pending_count": pending_count},
        )
    except Exception:  # noqa: BLE001 -- logging must never fail closed-in-the-wrong-direction
        pass


def _log_opportunity_selection_failure(range_start: datetime, session_name, exc: Exception) -> None:
    try:
        _logger.error(
            "opportunity_selection_failure",
            extra={"range_start": range_start.isoformat(), "session_name": session_name.value, "error": repr(exc)},
        )
    except Exception:  # noqa: BLE001
        pass


__all__ = ["RuntimeOrchestrator", "BridgeSubmit"]
