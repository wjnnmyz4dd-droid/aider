"""Runtime Orchestrator (Phase 3A, ADR-031).

`RuntimeOrchestrator` is the ONLY live coordinator. It owns ZERO
trading logic -- every conditional branch below is an equality/
membership check against a value another engine's public interface
already returned, never a threshold, weight, or rule computed inline
(ADR-031 SS2, verified structurally by this package's own architecture
test). It executes Evidence -> Market Intelligence -> Strategy ->
Risk -> Compliance -> Bridge in that fixed order, stopping a pair's
cycle immediately at the first rejection (ADR-031 SS3). Validation
Engine is never imported here -- it never participates in live
execution."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from titan_protocol.bridge.models import ErrorCode, TradeCommand
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import AccountState, ComplianceDecision
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import Bar
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs, NewsEvent
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import PortfolioState, TradeHistory
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import TradeIntent

from .bridge_handoff import build_trade_command
from .config import RUNTIME_VERSION, RuntimeConfig
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
        started_at = now
        stage_timings: List[StageTiming] = []
        last_stage: Optional[CycleStage] = None

        def _record(
            outcome: CycleOutcome,
            stage_reached: Optional[CycleStage],
            evidence_id: Optional[str] = None,
            selected_strategy=None,
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
            # `ended_at` is the same caller-supplied `now`, never a fresh
            # `datetime.now()` read -- Runtime has exactly one notion of
            # "now" per cycle (every engine it calls also takes a single
            # `now`), so decision-relevant fields stay fully deterministic.
            # `duration_ms`/`stage_timings` are real wall-clock processing
            # telemetry (`time.monotonic()`) and are expected to vary
            # between runs -- they are operational metrics, not decisions.
            ended_at = now
            duration_ms = sum(t.duration_ms for t in stage_timings)

            # Final Release Hardening (requirement 4) -- every field below
            # records an already-computed value from the snapshot passed
            # in by whichever call site reached that far; no new decision
            # logic is evaluated here, only extraction and hashing.
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

        try:
            if not profile.trading_window.contains(now):
                return _record(CycleOutcome.OUTSIDE_TRADING_WINDOW, None, reasons=("outside configured trading window",))

            last_stage = CycleStage.EVIDENCE
            stage_start = time.monotonic()
            evidence = self.evidence_engine.evaluate_snapshot(pair, bars, now)
            stage_timings.append(StageTiming(CycleStage.EVIDENCE, (time.monotonic() - stage_start) * 1000.0))
            evidence_id = f"{pair}:{evidence.report.generated_at.isoformat()}"

            if profile.session_rules and evidence.session.session not in profile.session_rules:
                return _record(
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

            if strategy.rejected:
                return _record(
                    CycleOutcome.NO_STRATEGY, CycleStage.STRATEGY, evidence_id=evidence_id,
                    reasons=(strategy.rejection_reason or "no strategy qualified",),
                    evidence=evidence, market_intelligence=market_intelligence,
                )

            last_stage = CycleStage.RISK
            stage_start = time.monotonic()
            risk = self.risk_engine.evaluate(pair, evidence, market_intelligence, strategy, portfolio_state, trade_history, now)
            stage_timings.append(StageTiming(CycleStage.RISK, (time.monotonic() - stage_start) * 1000.0))

            if not risk.approved:
                return _record(
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
                return _record(
                    CycleOutcome.COMPLIANCE_REJECTED, CycleStage.COMPLIANCE, evidence_id=evidence_id,
                    selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                    risk_approved=True, compliance_decision=compliance.decision, reasons=(compliance.reason,),
                    evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                )

            last_stage = CycleStage.BRIDGE
            stage_start = time.monotonic()
            bridge_error: Optional[ErrorCode] = None
            command = None
            if self.bridge_submit is not None and compliance.ready_for_bridge:
                command = build_trade_command(pair, strategy, risk, compliance, cycle_id, now, self.config)
                bridge_error = self.bridge_submit(command, now)
            stage_timings.append(StageTiming(CycleStage.BRIDGE, (time.monotonic() - stage_start) * 1000.0))
            bridge_correlation_id = command.correlation_id if command is not None else None

            if bridge_error is not None:
                return _record(
                    CycleOutcome.BRIDGE_ERROR, CycleStage.BRIDGE, evidence_id=evidence_id,
                    selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                    risk_approved=True, compliance_decision=compliance.decision, bridge_error=bridge_error,
                    reasons=(bridge_error.value,),
                    evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                    bridge_correlation_id=bridge_correlation_id,
                )

            return _record(
                CycleOutcome.SUBMITTED, CycleStage.BRIDGE, evidence_id=evidence_id,
                selected_strategy=strategy.winning_strategy.strategy_id, trade_intent=strategy.trade_intent,
                risk_approved=True, compliance_decision=compliance.decision, reasons=(compliance.reason,),
                evidence=evidence, market_intelligence=market_intelligence, risk=risk, compliance=compliance,
                bridge_correlation_id=bridge_correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 -- fail closed, never propagate a partial cycle
            if self.metrics is not None:
                self.metrics.record_failure()
            return _record(CycleOutcome.FAILED, last_stage, reasons=(repr(exc),))
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
        before any engine is called."""

        started_at = now
        records = []
        for pair in sorted(pairs):
            if pair not in profile.allowed_pairs:
                continue
            (bars, events, current_spread, average_spread, market_safety_inputs,
             portfolio_state, trade_history, account_state) = inputs[pair]
            records.append(self.run_cycle_for_pair(
                pair, bars, events, current_spread, average_spread, market_safety_inputs,
                portfolio_state, trade_history, account_state, profile, now, cycle_id,
            ))

        ended_at = now  # same single caller-supplied clock reading, never a fresh wall-clock read (determinism)
        total_duration_ms = sum(r.duration_ms for r in records)
        return CycleReport(cycle_id=cycle_id, started_at=started_at, ended_at=ended_at, duration_ms=total_duration_ms, records=tuple(records))


__all__ = ["RuntimeOrchestrator", "BridgeSubmit"]
