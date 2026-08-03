"""Versioned configuration for the Phantom AI Research Desk (`ADR-021`).

Every tunable here is an implementation default naming *how* this
package's own read-only analysis behaves, never new architecture
(`CLAUDE.md` §7, §3).
"""

from __future__ import annotations

from dataclasses import dataclass

RESEARCH_DESK_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class ResearchDeskConfig:
    recent_summaries_limit: int = 10
    recent_trends_limit: int = 10
    recurring_mistake_min_occurrences: int = 2
    rule_combination_min_occurrences: int = 2


DEFAULT_CONFIG = ResearchDeskConfig()

__all__ = ["RESEARCH_DESK_VERSION", "ResearchDeskConfig", "DEFAULT_CONFIG"]
