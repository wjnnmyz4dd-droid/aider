"""`ResearchEngine` -- the Research & Learning Engine's orchestrator
(Phase 2F). Completely advisory: never places, rejects, sizes, or
modifies live behavior (ADR-029 §1).

Thread safety: `ResearchEngine` holds no mutable state beyond
`config`/`metrics` -- a pure, stateless, read-only function of
`ClosedTradeHistory`, mirroring `ADR-028`'s `ComplianceEngine`
precedent (ADR-029 Hard Rule 2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from .attribution import DIMENSION_KEY_FUNCS, attribute_all_dimensions, compute_bucket_statistics
from .config import ResearchEngineConfig
from .execution_quality import summarize_execution_quality
from .explainability import build_research_snapshot
from .logging_sink import log_research_snapshot
from .metrics import ResearchEngineMetrics
from .models import (
    AttributionDimension,
    ClosedTradeHistory,
    EffectivenessComparison,
    Recommendation,
    ReportPeriod,
    ResearchSnapshot,
    executed_trades,
)
from .pair_intelligence import rank_pairs
from .recommendations import cross_dimension_recommendations, recommendations_from_attribution
from .reporting import filter_trades_by_period, period_bounds
from .reviews import review_compliance, review_market_intelligence, review_risk
from .session_intelligence import rank_sessions
from .strategy_intelligence import rank_strategies


def _wrap_text_recommendations(texts, dimension: str) -> List[Recommendation]:
    return [Recommendation(text=text, supporting_dimension=dimension, supporting_data="", confidence="MEDIUM") for text in texts]


class ResearchEngine:
    def __init__(self, config: ResearchEngineConfig, metrics: Optional[ResearchEngineMetrics] = None) -> None:
        self.config = config
        self.metrics = metrics

    def evaluate(
        self,
        closed_trade_history: ClosedTradeHistory,
        period: ReportPeriod = ReportPeriod.CUSTOM,
        now: Optional[datetime] = None,
        custom_start: Optional[datetime] = None,
        custom_end: Optional[datetime] = None,
    ) -> ResearchSnapshot:
        now = now or datetime.now(timezone.utc)
        start, end = period_bounds(period, now, custom_start, custom_end)

        all_trades_in_period = filter_trades_by_period(closed_trade_history.results, start, end)
        executed = executed_trades(all_trades_in_period)

        warnings = []
        if not all_trades_in_period:
            warnings.append("No trades found in the requested period.")
        elif not executed:
            warnings.append("Every trade in the requested period was rejected -- no execution data to analyze.")

        pair_rankings = rank_pairs(executed, self.config)
        strategy_rankings = rank_strategies(executed, self.config)
        session_rankings = rank_sessions(executed, self.config)
        attributions = attribute_all_dimensions(executed, self.config)
        execution_quality = summarize_execution_quality(executed, self.config)

        overall_stats = compute_bucket_statistics(executed, self.config)
        overall_comparison = EffectivenessComparison(
            label="overall", baseline_sample_size=0, baseline_expectancy=None,
            comparison_sample_size=len(executed), comparison_expectancy=overall_stats.rolling_expectancy,
            delta=None, notable=False,
        )

        mi_review = review_market_intelligence(executed, self.config)
        risk_review_result = review_risk(executed, self.config)
        compliance_effectiveness = review_compliance(all_trades_in_period, self.config)

        recommendations: List[Recommendation] = []
        recommendations += recommendations_from_attribution(attributions, overall_comparison, self.config)
        recommendations += cross_dimension_recommendations(
            executed, DIMENSION_KEY_FUNCS[AttributionDimension.SESSION], "session", self.config,
        )
        recommendations += cross_dimension_recommendations(
            executed, DIMENSION_KEY_FUNCS[AttributionDimension.VOLATILITY_BUCKET], "volatility_bucket", self.config,
        )
        recommendations += cross_dimension_recommendations(
            executed, DIMENSION_KEY_FUNCS[AttributionDimension.NEWS_CATEGORY], "news_category", self.config,
        )
        recommendations += _wrap_text_recommendations(mi_review.recommendations, "MARKET_INTELLIGENCE_REVIEW")
        recommendations += _wrap_text_recommendations(risk_review_result.recommendations, "RISK_REVIEW")
        recommendations += _wrap_text_recommendations(compliance_effectiveness.recommendations, "COMPLIANCE_REVIEW")
        recommendations.sort(key=lambda r: r.text)

        snapshot = build_research_snapshot(
            generated_at=now, period=period, period_start=start, period_end=end, sample_size=len(executed),
            pair_rankings=pair_rankings, strategy_rankings=strategy_rankings, session_rankings=session_rankings,
            attributions=attributions, execution_quality=execution_quality, market_intelligence_review=mi_review,
            risk_review=risk_review_result, compliance_effectiveness=compliance_effectiveness,
            recommendations=tuple(recommendations), warnings=tuple(warnings),
        )
        log_research_snapshot(snapshot)
        if self.metrics is not None:
            self.metrics.record_evaluation()
            self.metrics.record_recommendations(len(recommendations))
        return snapshot


__all__ = ["ResearchEngine"]
