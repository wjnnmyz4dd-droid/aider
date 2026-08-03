"""Phantom AI Research Desk (`ADR-021`).

**Not a 17th pipeline stage.** Exactly like Watchdog (`ADR-011`),
Dashboard (`ADR-012`), and the Knowledge & RAG subsystem (`ADR-020`),
this package is a cross-cutting observer with no position in the
trading decision chain and no decision, execution, risk, compliance, or
scoring authority. It sits one layer above `phantom_pipeline.knowledge`,
which it reuses wholesale for retrieval/indexing rather than duplicating
(`ADR-021` §2) — no pipeline-stage package imports either
(`scripts/check_architecture.py` enforces this for both).

See `docs/adr/ADR-021-ai-research-desk.md` and
`docs/plans/ai-research-desk.md` for the full research/plan record.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, RESEARCH_DESK_VERSION, ResearchDeskConfig
from .debate import BullBearDebateAgent
from .dashboard import ResearchDeskDashboardBuilder
from .explainable import ExplainableDecisionEngine
from .institutional_review import WeeklyInstitutionalReviewGenerator
from .market_research import MarketResearchAgent
from .metrics import ResearchDeskMetrics
from .models import (
    SCHEMA_VERSION,
    ComparisonReport,
    DebateStance,
    DebateThesis,
    InstitutionalReviewReport,
    JournalEntry,
    MarketResearchReport,
    MarketStructureFinding,
    ParameterSensitivityResult,
    RecurringMistake,
    ResearchDeskDashboardSnapshot,
    RuleCombinationFinding,
    ThesisCase,
    TradeThesis,
)
from .strategy_research import StrategyResearchAgent
from .trade_journal import AITradeJournal
from .trade_thesis import TradeThesisGenerator

__all__ = [
    "SCHEMA_VERSION",
    "RESEARCH_DESK_VERSION",
    "ResearchDeskConfig",
    "DEFAULT_CONFIG",
    "DebateStance",
    "ThesisCase",
    "DebateThesis",
    "MarketStructureFinding",
    "MarketResearchReport",
    "TradeThesis",
    "JournalEntry",
    "RuleCombinationFinding",
    "ParameterSensitivityResult",
    "RecurringMistake",
    "InstitutionalReviewReport",
    "ComparisonReport",
    "ResearchDeskDashboardSnapshot",
    "MarketResearchAgent",
    "BullBearDebateAgent",
    "TradeThesisGenerator",
    "AITradeJournal",
    "StrategyResearchAgent",
    "WeeklyInstitutionalReviewGenerator",
    "ExplainableDecisionEngine",
    "ResearchDeskDashboardBuilder",
    "ResearchDeskMetrics",
]
