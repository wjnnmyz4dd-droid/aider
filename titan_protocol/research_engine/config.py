"""Configuration for the Research & Learning Engine (Phase 2F).

Every threshold used anywhere in this package is named here -- no
magic numbers embedded in the analysis modules (CLAUDE.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass

RESEARCH_ENGINE_VERSION = "1.0.0-phase2f"


@dataclass(frozen=True)
class ResearchEngineConfig:
    # -- Ranking / attribution sample-size thresholds --
    min_sample_size_for_ranking: int = 10
    bucket_statistics_min_sample_size: int = 5  # passed to the reused risk_engine.statistics call
    #: Bucket-level statistics reuse `risk_engine.statistics`'s Monte-Carlo-based
    #: risk-of-ruin estimate (ADR-029 §0) -- kept deliberately cheap here since
    #: dozens of buckets are computed per `evaluate()` call, unlike Risk Engine's
    #: own single-pair-at-a-time usage.
    bucket_risk_of_ruin_simulations: int = 200
    bucket_monte_carlo_sequence_length: int = 20

    # -- Recommendation generation (deterministic, threshold-based only) --
    min_sample_size_for_recommendation: int = 10
    recommendation_expectancy_delta_threshold: float = 0.3  # R units
    recommendation_win_rate_delta_threshold: float = 0.15  # 0-1 fraction
    high_confidence_sample_size: int = 30
    medium_confidence_sample_size: int = 15

    # -- Execution Quality Score weights (sum to 1.0) --
    slippage_weight: float = 0.35
    fill_time_weight: float = 0.25
    requote_weight: float = 0.15
    stop_tp_execution_weight: float = 0.25

    max_acceptable_slippage_pips: float = 3.0
    max_acceptable_fill_time_ms: float = 2000.0
    requote_penalty_per_event: float = 10.0
    stop_execution_tolerance_pips: float = 1.0
    tp_execution_tolerance_pips: float = 1.0

    # -- Effectiveness comparisons --
    effectiveness_min_sample_size: int = 5
    effectiveness_notable_delta_threshold: float = 0.2  # R units


__all__ = ["RESEARCH_ENGINE_VERSION", "ResearchEngineConfig"]
