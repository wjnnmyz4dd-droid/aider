"""Performance Analytics Agent (OFFLINE; no live authority).

Trade-outcome analysis, regime/liquidity/news-condition breakdowns,
execution-quality analysis, strategy-drift detection. Reads the shared memory
layer only; produces structured reports. It NEVER modifies production and is not
in the live decision path.
"""

from __future__ import annotations

from ..contract import SCHEMA_VERSION

LIVE_AUTHORITY = False


class PerformanceAnalyticsAgent:
    agent_id = "performance_analytics"
    agent_version = "0.1.0"
    uses_llm = False                     # deterministic analytics

    def __init__(self, memory):
        self.memory = memory             # the ONE shared memory store (read-only use)

    def report(self, subject=None, correlation_id=None):
        """Aggregate execution outcomes / decisions from memory into a report.
        Read-only; changes nothing."""
        outcomes = self.memory.query(kind="execution_outcome", subject=subject,
                                     correlation_id=correlation_id)
        decisions = self.memory.query(kind="strategy_decision", subject=subject,
                                      correlation_id=correlation_id)
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "subject": subject,
            "counts": {"execution_outcomes": len(outcomes),
                       "strategy_decisions": len(decisions)},
            "read_only": True,
            "modifies_production": False,
        }
