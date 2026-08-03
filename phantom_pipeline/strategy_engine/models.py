"""Strategy Engine output objects (ADR-003 §6).

`CandidateTrade` is the Strategy Engine's sole output type: a trade
*hypothesis*, never a decision. Every object here is an immutable (frozen)
dataclass. No field anywhere in this module is capable of representing a
score, ranking, approval, rejection, risk allocation, lot size, stop
loss/take profit, compliance verdict, or execution instruction (ADR-003
§6's type-level guarantee) — see
tests/phantom_pipeline/strategy_engine/test_engine.py's
`TestBoundaryTypeLevel` for the enforcement test.

`Direction` is reused directly from `phantom_pipeline.scanner.models`
rather than redefined here: a candidate's direction hypothesis and a
Scanner trend's direction fact share the same UP/DOWN/NEUTRAL/UNKNOWN
vocabulary, and importing the Scanner's own type at this data-model
boundary is not "computing a new market fact" (ADR-003 §11's forbidden
duplication) — it is simply reusing the existing fact-shaped type
Strategy Engine already depends on to receive `ScannerObservation`
in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Tuple

from ..data_pipeline.trace import make_trace_id
from ..scanner.models import Direction

SCHEMA_VERSION = 1


def make_candidate_id(
    observation_trace_id: str, strategy_id: str, strategy_version: str, disambiguator: str = "0"
) -> str:
    """The single, shared definition of a `CandidateTrade.candidate_id` —
    every playbook calls this rather than deriving its own hash, the same
    "compute once, share the result" discipline `ADR-002` §13 established.
    Deterministic: identical arguments always produce the same id."""

    return make_trace_id("candidate", observation_trace_id, strategy_id, strategy_version, disambiguator)


@dataclass(frozen=True)
class SupportingObservation:
    """A reference to the specific `ScannerObservation` fact that
    triggered this hypothesis (ADR-003 §6) — a pointer, not a copy."""

    field: str
    detail: str


@dataclass(frozen=True)
class Evidence:
    """Structured data backing the hypothesis (ADR-003 §6) — descriptive
    only, never a numeric confidence/score value."""

    key: str
    value: str


@dataclass(frozen=True)
class CandidateTrade:
    """One trade hypothesis (ADR-003 §6). Immutable once produced; later
    stages attach their own data alongside it, never rewrite it.

    `trace_id` is the propagated Scanner `trace_id` verbatim (ADR-003
    §12: "every record shares the trace_id established at the Scanner
    stage"), preserving upstream trace lineage directly rather than
    deriving a new hash from it. `candidate_id` is this specific
    candidate's own deterministic, content-derived identifier —
    distinguishing multiple candidates that share one `trace_id` (e.g.
    two playbooks both firing on the same observation).
    """

    schema_version: int
    trace_id: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    timestamp: datetime
    direction: Direction
    entry_concept: str
    supporting_observations: Tuple[SupportingObservation, ...]
    evidence: Tuple[Evidence, ...]
    reason_codes: Tuple[str, ...]
    reasoning: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "supporting_observations", tuple(self.supporting_observations)
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
