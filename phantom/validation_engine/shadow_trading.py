"""Shadow Trading (ADR-030 §5.6): production configuration vs. candidate
configuration, same historical market, no capital, comparison only. A
2-way Configuration Tournament under the hood, reusing
`research_engine.effectiveness.compare_buckets` -- never a second
comparison implementation (ADR-030 Hard Rule 5)."""

from __future__ import annotations

from phantom.research_engine.attribution import compute_bucket_statistics
from phantom.research_engine.effectiveness import compare_buckets
from phantom.research_engine.models import executed_trades

from .config import ValidationEngineConfig
from .models import ConfigurationRun, ShadowComparisonResult, TournamentEntry


def run_shadow_comparison(
    production: ConfigurationRun, candidate: ConfigurationRun, config: ValidationEngineConfig,
) -> ShadowComparisonResult:
    production_trades = executed_trades(production.trades.results)
    candidate_trades = executed_trades(candidate.trades.results)

    production_stats = compute_bucket_statistics(production.trades.results, config.research_config)
    candidate_stats = compute_bucket_statistics(candidate.trades.results, config.research_config)

    production_entry = TournamentEntry(
        subject=production.profile.value, rank=0, sample_size=len(production_trades),
        statistics=production_stats, recovery_factor=production_stats.recovery_factor,
    )
    candidate_entry = TournamentEntry(
        subject=candidate.profile.value, rank=0, sample_size=len(candidate_trades),
        statistics=candidate_stats, recovery_factor=candidate_stats.recovery_factor,
    )

    comparison = compare_buckets("shadow_trading", production_trades, candidate_trades, config.research_config)

    if comparison.delta is None:
        recommendation = "Insufficient sample size in one or both configurations to draw a shadow-trading conclusion."
    elif comparison.notable and comparison.delta > 0:
        recommendation = (
            f"Candidate configuration ({candidate.profile.value}) outperformed production "
            f"({production.profile.value}) by {comparison.delta:.2f}R expectancy over the same "
            "historical window -- recommend operator review before promotion; no capital was risked "
            "and no configuration was changed by this comparison."
        )
    elif comparison.notable:
        recommendation = (
            f"Candidate configuration ({candidate.profile.value}) underperformed production "
            f"({production.profile.value}) by {abs(comparison.delta):.2f}R expectancy -- recommend "
            "against promotion."
        )
    else:
        recommendation = "No notable expectancy difference between production and candidate in this replay window."

    return ShadowComparisonResult(
        production=production_entry, candidate=candidate_entry,
        expectancy_delta=comparison.delta, notable=comparison.notable, recommendation=recommendation,
    )


__all__ = ["run_shadow_comparison"]
