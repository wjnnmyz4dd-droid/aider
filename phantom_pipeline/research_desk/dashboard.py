"""Research Desk Dashboard builder (`ADR-021` §3, item 9).

Wraps `knowledge.KnowledgeDashboardSnapshot` verbatim (`ADR-021` Hard
Rule 3) — never re-implements it. `dashboard/` (`ADR-012`) is untouched
(Hard Rule 4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from ..knowledge import KnowledgeDashboardSnapshot
from .config import DEFAULT_CONFIG, ResearchDeskConfig
from .models import ResearchDeskDashboardSnapshot, SCHEMA_VERSION


class ResearchDeskDashboardBuilder:
    def __init__(self, config: ResearchDeskConfig = DEFAULT_CONFIG) -> None:
        self._config = config

    def build(
        self,
        now: datetime,
        knowledge_snapshot: KnowledgeDashboardSnapshot,
        research_summaries: Sequence[str] = (),
        learning_trends: Sequence[str] = (),
        strategy_evolution: Sequence[str] = (),
        optimization_history: Sequence[str] = (),
    ) -> ResearchDeskDashboardSnapshot:
        return ResearchDeskDashboardSnapshot(
            schema_version=SCHEMA_VERSION,
            generated_at=now,
            knowledge_snapshot=knowledge_snapshot,
            research_summaries=tuple(research_summaries)[-self._config.recent_summaries_limit :],
            learning_trends=tuple(learning_trends)[-self._config.recent_trends_limit :],
            strategy_evolution=tuple(strategy_evolution),
            optimization_history=tuple(optimization_history),
        )


__all__ = ["ResearchDeskDashboardBuilder"]
