"""Independent Audit Report (ADR-030 §5.13): a human-readable narrative
built purely from an already-produced `ValidationSnapshot` -- no new
computation, pure text assembly, mirroring
`research_engine.explainability.build_research_snapshot`'s "pure
assembly" pattern."""

from __future__ import annotations

from .models import ValidationSnapshot


def build_independent_audit_report(snapshot: ValidationSnapshot) -> str:
    lines = [
        f"TITAN_PROTOCOL VALIDATION ENGINE -- INDEPENDENT AUDIT REPORT ({snapshot.generated_at.isoformat()})",
        f"Overall result: {'PASS' if snapshot.passed else 'FAIL'}",
        "",
        f"Replay verifications: {len(snapshot.replay_verifications)} scenario(s), "
        f"{sum(1 for v in snapshot.replay_verifications if v.passed)} passed",
        f"Determinism: {'deterministic' if snapshot.determinism_report.all_deterministic else 'NON-DETERMINISM DETECTED'} "
        f"across {len(snapshot.determinism_report.checks)} scenario(s)",
        f"Explainability: {'all engines explained' if snapshot.explainability_report.all_explained else 'MISSING EXPLANATIONS DETECTED'}",
        "",
        f"Strategy tournament: {len(snapshot.strategy_tournament)} ranked entries",
        f"Pair tournament: {len(snapshot.pair_tournament)} ranked entries",
        f"Session tournament: {len(snapshot.session_tournament)} ranked entries",
        f"Configuration tournament: {len(snapshot.configuration_tournament.entries)} ranked entries, "
        f"{len(snapshot.configuration_tournament.recommendations)} recommendation(s)",
    ]

    if snapshot.shadow_comparison is not None:
        lines.append(f"Shadow trading: {snapshot.shadow_comparison.recommendation}")

    if snapshot.stress_test_results:
        survived = sum(1 for r in snapshot.stress_test_results if r.survived)
        restricted = sum(1 for r in snapshot.stress_test_results if r.correctly_restricted)
        lines.append(
            f"Stress testing: {survived}/{len(snapshot.stress_test_results)} survived, "
            f"{restricted}/{len(snapshot.stress_test_results)} correctly restricted"
        )

    if snapshot.walk_forward_result is not None:
        lines.append(f"Walk-forward: {snapshot.walk_forward_result.degradation_detail}")

    if snapshot.monte_carlo_validation is not None:
        lines.append(
            f"Monte Carlo: {snapshot.monte_carlo_validation.simulations_run} simulations, "
            f"risk of ruin={snapshot.monte_carlo_validation.risk_of_ruin}"
        )

    lines.append(
        f"Drift detection: {'DEGRADATION DETECTED' if snapshot.drift_analysis.any_degradation_detected else 'no degradation detected'} "
        f"across {len(snapshot.drift_analysis.findings)} dimension bucket(s)"
    )
    lines.append(
        f"Confidence calibration: {'well-calibrated' if snapshot.confidence_calibration.well_calibrated else 'MISCALIBRATION DETECTED'}"
    )
    lines.append(
        f"Execution validation: {'passed' if snapshot.execution_validation.passed else 'VIOLATIONS DETECTED'} "
        f"({snapshot.execution_validation.records_checked} record(s) checked)"
    )

    if snapshot.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in snapshot.warnings)

    if snapshot.recommendations:
        lines.append("")
        lines.append("Recommendations (advisory only -- no change applied by this engine):")
        lines.extend(f"  - {r}" for r in snapshot.recommendations)

    return "\n".join(lines)


__all__ = ["build_independent_audit_report"]
