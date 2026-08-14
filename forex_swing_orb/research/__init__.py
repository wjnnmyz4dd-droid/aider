"""Session Edge — Research & Analytics framework (Phase 9B).

COMPLETELY SEPARATE from the production trading system and READ-ONLY. Nothing in
the production runtime (bridge, compliance, position, ea_mt5, producer, manage,
runtime, live, session, run_dir strategy) imports this package; deleting the whole
``research/`` tree changes production behaviour in NO way.

Single-owner rule (this package NEVER re-implements or duplicates ownership):
  * strategy decisions   -> run_dir SignalEngine (loaded read-only via the accepted
                            producer.strategy_adapter load path; never copied)
  * compliance / FTMO    -> forex_swing_orb.compliance (consumed / called, never re-derived)
  * position management   -> forex_swing_orb.position (consumed, never re-derived)
  * execution / transport -> bridge + EA logs (consumed, never re-derived)

Authority: ZERO. It never places/modifies a trade or stop, never touches MT5 or a
broker, never writes a bridge instruction, never bypasses compliance/producer/
manager. It computes only NEW analytics (portfolio/execution statistics, walk-
forward, Monte Carlo, reports) that no production module owns. No networking.

Determinism: no wall-clock inside experiments (timestamps are injected), no UUIDs,
randomness only via an explicit seed. Every experiment records full provenance.
"""

from __future__ import annotations

from .provenance import ExperimentRecord, git_head, ProvenanceError
from . import (portfolio, execution_analytics, reporting, walk_forward, montecarlo,
               lifecycle, quality_facts)
from .experiments import ExperimentManager, Experiment

__all__ = [
    "ExperimentRecord", "git_head", "ProvenanceError", "portfolio",
    "execution_analytics", "reporting", "walk_forward", "montecarlo", "lifecycle",
    "quality_facts", "ExperimentManager", "Experiment",
]
