"""Research Agent (OFFLINE; no live authority).

Strategy research, hypothesis generation, backtest review, parameter proposals.
It NEVER modifies production automatically and is NOT wired into the live
orchestrator. Proposals are structured records for a future governed review.
"""

from __future__ import annotations

from ..contract import SCHEMA_VERSION

LIVE_AUTHORITY = False


class ResearchAgent:
    agent_id = "research"
    agent_version = "0.1.0"
    uses_llm = True                      # LLM-eligible (offline reasoning)

    def __init__(self, llm=None):
        self.llm = llm

    def propose(self, hypothesis, evidence=None):
        """Return a structured, non-binding proposal. Applying it requires a
        separate governed process — this method never changes any live rule."""
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "kind": "parameter_proposal",
            "hypothesis": hypothesis,
            "evidence": evidence or {},
            "applies_automatically": False,       # hard: never auto-applied
            "requires_governed_approval": True,
        }
