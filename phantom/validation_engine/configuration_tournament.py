"""Configuration Tournament (ADR-030 §5.5): ranks candidate configuration
profiles (Conservative/Balanced/Aggressive/London Focus/New York Focus/
Trend Focus/Range Focus/Custom) by replayed expectancy. Statistics come
from `research_engine.attribution.compute_bucket_statistics` -- never a
second implementation (ADR-030 Hard Rule 5). Recommendations only --
no configuration is ever changed here (Hard Rule 2)."""

from __future__ import annotations

from typing import Sequence, Tuple

from phantom.research_engine.attribution import compute_bucket_statistics
from phantom.research_engine.models import executed_trades

from .config import ValidationEngineConfig
from .models import ConfigurationRun, ConfigurationTournamentResult, TournamentEntry


def run_configuration_tournament(
    runs: Sequence[ConfigurationRun], config: ValidationEngineConfig,
) -> ConfigurationTournamentResult:
    entries = []
    for run in runs:
        executed = executed_trades(run.trades.results)
        if len(executed) < config.research_config.min_sample_size_for_ranking:
            continue
        stats = compute_bucket_statistics(run.trades.results, config.research_config)
        entries.append((run.profile.value, len(executed), stats))

    def sort_key(entry):
        _, sample_size, stats = entry
        expectancy = stats.rolling_expectancy if stats.rolling_expectancy is not None else float("-inf")
        return (-expectancy, -sample_size, entry[0])

    entries.sort(key=sort_key)
    ranked = tuple(
        TournamentEntry(subject=subject, rank=i + 1, sample_size=size, statistics=stats, recovery_factor=stats.recovery_factor)
        for i, (subject, size, stats) in enumerate(entries)
    )

    recommendations: Tuple[str, ...] = ()
    if len(ranked) >= 2:
        best, worst = ranked[0], ranked[-1]
        if best.statistics.rolling_expectancy is not None and worst.statistics.rolling_expectancy is not None:
            delta = best.statistics.rolling_expectancy - worst.statistics.rolling_expectancy
            if delta >= config.effectiveness_notable_delta_threshold:
                recommendations = (
                    f"{best.subject} produced the highest replayed expectancy "
                    f"({best.statistics.rolling_expectancy:.2f}R, n={best.sample_size}) versus "
                    f"{worst.subject} ({worst.statistics.rolling_expectancy:.2f}R, n={worst.sample_size}) "
                    "in this replay window -- recommend operator review before any promotion; "
                    "this engine does not apply configuration changes itself.",
                )

    return ConfigurationTournamentResult(entries=ranked, recommendations=recommendations)


__all__ = ["run_configuration_tournament"]
