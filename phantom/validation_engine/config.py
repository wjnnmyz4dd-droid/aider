"""Configuration for the Validation Engine (Phase 2G, ADR-030)."""

from __future__ import annotations

from dataclasses import dataclass, field

from phantom.research_engine.config import ResearchEngineConfig

VALIDATION_ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class ValidationEngineConfig:
    # Reused for every research_engine.* call this package makes (§0) --
    # a dedicated instance rather than defaulting to research_engine's
    # own tuning, so this package's sample-size/threshold choices never
    # silently drift with Research Engine's own config changes.
    research_config: ResearchEngineConfig = field(default_factory=ResearchEngineConfig)

    determinism_repeat_count: int = 3

    # Walk-forward / drift / calibration thresholds.
    degradation_expectancy_delta_threshold: float = 0.3  # R units, worse than baseline
    min_sample_size_for_walk_forward_bucket: int = 5
    min_sample_size_for_drift_bucket: int = 5
    min_sample_size_for_calibration_tier: int = 5
    execution_quality_degradation_threshold: float = 10.0  # composite score points

    # Execution validation sanity bound.
    max_acceptable_slippage_pips: float = 10.0

    # Shadow trading / configuration tournament.
    effectiveness_notable_delta_threshold: float = 0.2  # R units, mirrors research_engine's own default


__all__ = ["VALIDATION_ENGINE_VERSION", "ValidationEngineConfig"]
