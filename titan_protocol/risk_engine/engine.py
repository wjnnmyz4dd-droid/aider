"""`RiskEngine` -- the Portfolio Statistical Risk Engine's orchestrator
(Phase 2D).

Consumes an `EvidenceSnapshot` (ADR-024), a `MarketIntelligenceSnapshot`
(ADR-025), and a `StrategySnapshot` (ADR-026) for one pair -- plus two
optional, caller-supplied inputs, `PortfolioState` and `TradeHistory`
(ADR-027 §0a) -- and produces a `RiskSnapshot`. Never decides direction,
strategy selection, trade execution, news approval, or compliance
(ADR-027 §1).

Thread safety: `RiskEngine` holds one `ReservationLedger`, guarded by
its own internal lock (`reservation.py`) -- every `evaluate()` call's
exposure check and reservation happen as one atomic step through
`ReservationLedger.reserve_if()`, so concurrent calls can never
together approve more risk than the configured limits allow (ADR-027
Hard Rule 5). Every other computation in this module is a pure function
of its inputs; no other mutable state is held.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from titan_protocol.evidence_engine.models import EvidenceSnapshot
from titan_protocol.market_intelligence.models import MarketIntelligenceSnapshot
from titan_protocol.strategy_engine.models import StrategySnapshot

from .config import RiskEngineConfig
from .confidence import confidence_tier_for_evidence_score
from .correlation import compute_correlation_status
from .exposure import compute_exposure_summary
from .explainability import build_risk_snapshot
from .gate import check_evidence_gate
from .logging_sink import log_risk_snapshot
from .metrics import RiskEngineMetrics
from .models import MonteCarloResult, PortfolioState, RejectionReason, RiskSnapshot, StatisticalMetrics, TradeHistory
from .monte_carlo import run_monte_carlo
from .position_sizing import compute_position_size
from .reservation import ReservationLedger
from .safety_limits import check_safety_limits
from .statistics import compute_statistical_metrics
from .volatility import compute_volatility_adjustment


class RiskEngine:
    def __init__(self, config: RiskEngineConfig, metrics: Optional[RiskEngineMetrics] = None) -> None:
        self.config = config
        self.metrics = metrics
        self._ledger = ReservationLedger()

    def _reject(self, pair: str, now: datetime, reason: RejectionReason) -> RiskSnapshot:
        snapshot = build_risk_snapshot(
            pair=pair, now=now, approved=False, rejection_reason=reason,
            confidence_tier=None, volatility_adjustment=None, exposure_summary=None,
            correlation_status=None, statistical_metrics=None, monte_carlo=None,
            recommended_position_size=None, reservation_id=None,
        )
        log_risk_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            self.metrics.record_rejection()
        return snapshot

    def evaluate(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        strategy: StrategySnapshot,
        portfolio_state: Optional[PortfolioState] = None,
        trade_history: Optional[TradeHistory] = None,
        now: Optional[datetime] = None,
    ) -> RiskSnapshot:
        statistical_metrics = compute_statistical_metrics(trade_history, self.config)
        monte_carlo = run_monte_carlo(trade_history, self.config)
        return self._evaluate(
            pair, evidence, market_intelligence, strategy, portfolio_state, trade_history,
            now, statistical_metrics, monte_carlo,
        )

    def _evaluate(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        strategy: StrategySnapshot,
        portfolio_state: Optional[PortfolioState],
        trade_history: Optional[TradeHistory],
        now: Optional[datetime],
        statistical_metrics: StatisticalMetrics,
        monte_carlo: Optional[MonteCarloResult],
    ) -> RiskSnapshot:
        """Shared core -- `evaluate()` computes `statistical_metrics`/
        `monte_carlo` fresh (both depend only on `trade_history` and
        `self.config`, never on `pair`); `evaluate_batch()` computes them
        exactly once per call and passes the same values into every pair,
        rather than recomputing an identical Monte Carlo simulation once
        per pair in the batch (ADR-027 Hard Rule 8: no duplicate
        calculations)."""

        if evidence.report.symbol != pair:
            raise ValueError(f"evidence.report.symbol ({evidence.report.symbol!r}) does not match pair ({pair!r})")
        if market_intelligence.pair != pair:
            raise ValueError(f"market_intelligence.pair ({market_intelligence.pair!r}) does not match pair ({pair!r})")
        if strategy.pair != pair:
            raise ValueError(f"strategy.pair ({strategy.pair!r}) does not match pair ({pair!r})")
        now = now or evidence.report.generated_at or datetime.now(timezone.utc)

        # 1. The 65-point evidence gate (ADR-027 Hard Rule 1) -- below it,
        # nothing else in this package is computed.
        gate_rejection = check_evidence_gate(evidence, self.config)
        if gate_rejection is not None:
            return self._reject(pair, now, gate_rejection)

        # 2. No qualified strategy, nothing to size.
        if strategy.rejected or strategy.winning_strategy is None:
            return self._reject(pair, now, RejectionReason.NO_QUALIFIED_STRATEGY)

        confidence_tier = confidence_tier_for_evidence_score(evidence.report.score.composite, self.config)
        if confidence_tier is None:
            confidence_tier = self.config.fail_closed_tier

        volatility_adjustment = compute_volatility_adjustment(
            evidence.volatility, market_intelligence.pair_safety.liquidity, self.config,
        )
        candidate_sizing = compute_position_size(confidence_tier, volatility_adjustment, statistical_metrics, self.config)
        candidate_risk_r = candidate_sizing.final_r

        captured: Dict[str, object] = {}

        def _predicate(pending_reservations: Tuple) -> bool:
            exposure_summary = compute_exposure_summary(portfolio_state, pending_reservations)
            correlation_status = compute_correlation_status(pair, portfolio_state, trade_history, self.config)
            rejection, limit_warnings = check_safety_limits(
                pair, candidate_risk_r, portfolio_state, trade_history,
                exposure_summary, correlation_status, self.config, now,
            )
            captured["exposure_summary"] = exposure_summary
            captured["correlation_status"] = correlation_status
            captured["rejection"] = rejection
            captured["warnings"] = limit_warnings
            return rejection is None

        reservation_id = self._ledger.reserve_if(pair, candidate_risk_r, _predicate)

        if reservation_id is None:
            snapshot = build_risk_snapshot(
                pair=pair, now=now, approved=False, rejection_reason=captured["rejection"],
                confidence_tier=confidence_tier, volatility_adjustment=volatility_adjustment,
                exposure_summary=captured["exposure_summary"], correlation_status=captured["correlation_status"],
                statistical_metrics=statistical_metrics, monte_carlo=monte_carlo,
                recommended_position_size=None, reservation_id=None,
                extra_warnings=captured["warnings"],
            )
            log_risk_snapshot(snapshot)
            if self.metrics is not None:
                self.metrics.record_evaluation()
                self.metrics.record_rejection()
            return snapshot

        snapshot = build_risk_snapshot(
            pair=pair, now=now, approved=True, rejection_reason=None,
            confidence_tier=confidence_tier, volatility_adjustment=volatility_adjustment,
            exposure_summary=captured["exposure_summary"], correlation_status=captured["correlation_status"],
            statistical_metrics=statistical_metrics, monte_carlo=monte_carlo,
            recommended_position_size=candidate_sizing, reservation_id=reservation_id,
            extra_warnings=captured["warnings"],
        )
        log_risk_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            self.metrics.record_approval()
        return snapshot

    def release_reservation(self, reservation_id: str) -> bool:
        """Releases a pending reservation -- call this once a
        downstream stage rejects the trade, or once `PortfolioState`
        has been updated to reflect the position as genuinely open (so
        it is never counted twice). Idempotent: releasing an
        already-released or unknown reservation_id is a harmless no-op
        (returns `False`), never an error -- callers (Runtime's
        InFlightCommandRegistry-driven release points) never need to
        track whether they already released a given id."""

        return self._ledger.release(reservation_id)

    def pending_reservation_count(self) -> int:
        """Health-diagnostic passthrough -- the number of reservations
        currently held open (approved trades whose ownership has not
        yet transferred to a resolved/released state). A number that
        only ever grows across a long-running process indicates the
        release wiring has a gap -- see health_check.py's RUN STATUS
        panel."""
        return len(self._ledger)

    def pending_reservation_total_r(self) -> float:
        """Health-diagnostic passthrough -- the total R currently held
        in open reservations, the same value every `evaluate()` call's
        own exposure check already sees via `pending_total_r()`."""
        return self._ledger.pending_total_r()

    def evaluate_batch(
        self,
        pairs: Dict[str, Tuple[EvidenceSnapshot, MarketIntelligenceSnapshot, StrategySnapshot]],
        portfolio_state: Optional[PortfolioState] = None,
        trade_history: Optional[TradeHistory] = None,
        now: Optional[datetime] = None,
    ) -> Tuple[RiskSnapshot, ...]:
        """Evaluates every pair, sorted by symbol for determinism.
        `pairs[pair]` is `(evidence_snapshot, market_intelligence_snapshot, strategy_snapshot)`."""

        # Computed once for the whole batch -- both depend only on
        # `trade_history`/`self.config`, never on the pair being
        # evaluated, so recomputing per pair would be a duplicate
        # calculation (ADR-027 Hard Rule 8).
        statistical_metrics = compute_statistical_metrics(trade_history, self.config)
        monte_carlo = run_monte_carlo(trade_history, self.config)

        results = tuple(
            self._evaluate(
                pair, evidence, market_intelligence, strategy, portfolio_state, trade_history,
                now, statistical_metrics, monte_carlo,
            )
            for pair, (evidence, market_intelligence, strategy) in sorted(pairs.items())
        )
        if self.metrics is not None:
            self.metrics.record_batch_evaluation()
        return results


__all__ = ["RiskEngine"]
