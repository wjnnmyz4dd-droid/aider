"""Validation Engine orchestrator (Phase 2G, ADR-030).

Stateless, like every prior engine this session: `__init__` assigns
only `self.config`/`self.metrics`. `evaluate()` is a pure function of
its caller-supplied inputs -- it never re-invokes the Evidence/Market
Intelligence/Strategy/Risk/Compliance/Research engines' own compute
logic (ADR-030 Hard Rule 4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence

from phantom.research_engine.models import ClosedTradeHistory

from .audit import build_independent_audit_report
from .config import ValidationEngineConfig
from .confidence_calibration import run_confidence_calibration
from .configuration_tournament import run_configuration_tournament
from .determinism import check_determinism_for_run
from .drift_detection import detect_drift
from .execution_validation import validate_execution
from .explainability import build_explainability_report
from .logging_sink import log_validation_snapshot
from .metrics import ValidationEngineMetrics
from .models import ConfigurationRun, ConfigurationTournamentResult, DriftAnalysis, HistoricalRun, ValidationSnapshot
from .monte_carlo_validation import run_monte_carlo_validation
from .replay import verify_run
from .shadow_trading import run_shadow_comparison
from .stress_testing import run_stress_tests
from .tournament import run_pair_tournament, run_session_tournament, run_strategy_tournament
from .walk_forward import run_walk_forward


class ValidationEngine:
    def __init__(self, config: ValidationEngineConfig, metrics: Optional[ValidationEngineMetrics] = None) -> None:
        self.config = config
        self.metrics = metrics

    def evaluate(
        self,
        run: HistoricalRun,
        closed_trades: ClosedTradeHistory,
        configuration_runs: Sequence[ConfigurationRun] = (),
        shadow_production: Optional[ConfigurationRun] = None,
        shadow_candidate: Optional[ConfigurationRun] = None,
        walk_forward_train_end: Optional[datetime] = None,
        walk_forward_validation_end: Optional[datetime] = None,
        drift_baseline: Optional[ClosedTradeHistory] = None,
        drift_current: Optional[ClosedTradeHistory] = None,
        now: Optional[datetime] = None,
    ) -> ValidationSnapshot:
        now = now or datetime.now(timezone.utc)
        warnings: List[str] = []

        replay_verifications = verify_run(run.scenarios)
        determinism_report = check_determinism_for_run(run.scenarios, self.config)
        explainability_report = build_explainability_report(run)
        stress_test_results = run_stress_tests(run.scenarios)
        execution_validation = validate_execution(run.scenarios, self.config)

        if not run.scenarios:
            warnings.append("No historical scenarios supplied -- replay/determinism/explainability/stress checks are vacuous.")

        if not closed_trades.results:
            warnings.append("No closed trades supplied -- tournaments, walk-forward, Monte Carlo, and calibration are empty.")

        strategy_tournament = run_strategy_tournament(closed_trades.results, self.config)
        pair_tournament = run_pair_tournament(closed_trades.results, self.config)
        session_tournament = run_session_tournament(closed_trades.results, self.config)

        configuration_tournament = (
            run_configuration_tournament(configuration_runs, self.config) if configuration_runs
            else ConfigurationTournamentResult(entries=(), recommendations=())
        )

        shadow_comparison = None
        if shadow_production is not None and shadow_candidate is not None:
            shadow_comparison = run_shadow_comparison(shadow_production, shadow_candidate, self.config)

        walk_forward_result = None
        if closed_trades.results:
            walk_forward_result = run_walk_forward(
                closed_trades.results, self.config, walk_forward_train_end, walk_forward_validation_end,
            )

        monte_carlo_validation = run_monte_carlo_validation(closed_trades.results, self.config)

        drift_analysis: DriftAnalysis
        if drift_baseline is not None and drift_current is not None:
            drift_analysis = detect_drift(drift_baseline.results, drift_current.results, self.config)
        else:
            drift_analysis = DriftAnalysis(findings=(), execution_quality_delta=None, any_degradation_detected=False)
            warnings.append("No drift baseline/current trade history supplied -- drift detection is vacuous.")

        confidence_calibration = run_confidence_calibration(closed_trades.results, self.config)

        recommendations: List[str] = list(configuration_tournament.recommendations)
        if shadow_comparison is not None and shadow_comparison.notable:
            recommendations.append(shadow_comparison.recommendation)
        if not confidence_calibration.well_calibrated:
            recommendations.extend(confidence_calibration.notes)
        for finding in drift_analysis.findings:
            if finding.degraded:
                recommendations.append(
                    f"{finding.dimension} {finding.subject} shows expectancy degradation "
                    f"({finding.delta:+.2f}R vs. baseline) -- recommend operator review."
                )
        recommendations.sort()

        passed = (
            all(v.passed for v in replay_verifications)
            and determinism_report.all_deterministic
            and explainability_report.all_explained
            and all(r.survived and r.correctly_restricted for r in stress_test_results)
            and (walk_forward_result is None or not walk_forward_result.degradation_detected)
            and not drift_analysis.any_degradation_detected
            and confidence_calibration.well_calibrated
            and execution_validation.passed
        )

        snapshot = ValidationSnapshot(
            generated_at=now, passed=passed, warnings=tuple(warnings), recommendations=tuple(recommendations),
            replay_verifications=replay_verifications, determinism_report=determinism_report,
            explainability_report=explainability_report,
            strategy_tournament=strategy_tournament, pair_tournament=pair_tournament, session_tournament=session_tournament,
            configuration_tournament=configuration_tournament, shadow_comparison=shadow_comparison,
            stress_test_results=stress_test_results, walk_forward_result=walk_forward_result,
            monte_carlo_validation=monte_carlo_validation, drift_analysis=drift_analysis,
            confidence_calibration=confidence_calibration, execution_validation=execution_validation,
        )

        log_validation_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            if not passed:
                self.metrics.record_failure()
        return snapshot

    def build_audit_report(self, snapshot: ValidationSnapshot) -> str:
        return build_independent_audit_report(snapshot)


__all__ = ["ValidationEngine"]
