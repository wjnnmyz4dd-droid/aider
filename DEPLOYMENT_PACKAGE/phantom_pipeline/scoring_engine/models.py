"""Scoring Engine output objects (ADR-004 §6).

`ScoreResult` is the Scoring Engine's sole success output: advisory
strength/confidence information, never a decision. `ScoringFailureRecord`
is its deterministic failure counterpart (§8) — a `CandidateTrade` that
could not be scored still produces exactly one record, never a silent
drop (§7).

Every object here is an immutable (frozen) dataclass. No field anywhere
in this module is capable of representing a lot size, risk allocation,
compliance verdict, execution command, MT5 instruction, position-
management action, or broker action (ADR-004 §6's type-level guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Tuple

SCHEMA_VERSION = 1


class RuleOutcome(Enum):
    """A rule either fired (contributed points), abstained (a required
    input was absent/degraded — not a bug), or failed (a true
    implementation exception, caught and isolated by the engine, ADR-004
    §8). `FAILED` is set by the engine itself, never by a rule directly —
    a rule cannot both raise and return a value."""

    FIRED = "FIRED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ScoringEvidence:
    """A pointer to the specific `CandidateTrade` field that drove a
    rule's outcome — descriptive only, never itself a further score."""

    source_field: str
    detail: str


@dataclass(frozen=True)
class RuleContribution:
    """One scoring rule's evaluation of one `CandidateTrade` (ADR-004
    §5, §8). `points` is `0.0` whenever `outcome` is not `FIRED` — an
    abstained or failed rule contributes nothing to `overall_score`."""

    rule_id: str
    rule_version: str
    outcome: RuleOutcome
    points: float
    weight: float
    evidence: Tuple[ScoringEvidence, ...]
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class FactorBreakdown:
    """A named grouping of `RuleContribution`s (e.g. "evidence_strength",
    "directional_clarity") with its own subtotal — derived by summing the
    already-computed rule contributions belonging to this factor, never a
    second independent computation (ADR-004 §13)."""

    factor: str
    subtotal: float
    rule_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_ids", tuple(self.rule_ids))


@dataclass(frozen=True)
class ScoreResult:
    """One `CandidateTrade`'s score (ADR-004 §6). Immutable once
    produced; later stages attach their own data alongside it, never
    rewrite it.

    `trace_id` and `candidate_id` are the propagated Strategy Engine
    values verbatim, preserving the full trace lineage from Scanner
    through Strategy Engine into scoring (ADR-004 §3, §10)."""

    schema_version: int
    trace_id: str
    candidate_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    timestamp: datetime
    overall_score: float
    factor_breakdown: Tuple[FactorBreakdown, ...]
    rule_contributions: Tuple[RuleContribution, ...]
    confidence_rationale: str
    scoring_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "factor_breakdown", tuple(self.factor_breakdown))
        object.__setattr__(self, "rule_contributions", tuple(self.rule_contributions))


@dataclass(frozen=True)
class ScoringFailureRecord:
    """The deterministic failure record for a `CandidateTrade` that could
    not be scored at all (ADR-004 §4, §8) — e.g. an incompatible
    `schema_version` or a structurally malformed candidate. Still
    forwarded downstream: the Scoring Engine never silently drops a
    candidate (§7)."""

    schema_version: int
    trace_id: str
    candidate_id: str
    strategy_id: str
    reason: str
    scoring_version: str
