"""Execution Validator input/output objects (ADR-007 §2, §4).

`ExecutionDecision` is the Execution Validator's sole output type: a
final APPROVE/REJECT gate ("is this trade still valid right now"), never
a re-decision of strategy, score, sizing, or policy. Every input it
consumes (`ComplianceDecision`, `RiskDecision`, `ScoreResult`,
`CandidateTrade`, market/broker/account state) is read-only — this
module attaches a verdict alongside those objects, it never rewrites
them (ADR-007 §4, §13).

`AccountState`/`BrokerState` here are the Execution Validator's own,
freshly-read view of account/broker facts (ADR-007 §2) — distinct from
`risk_engine.models.AccountState` and `compliance_engine.models.
AccountState`, each of which is scoped to its own stage's needs. Current
market price/spread/`market_status` are read directly from `data_pipeline.
models.MarketSnapshot`, reused rather than duplicated, per `ADR-007` §2
and `INTERFACE_SPECIFICATION.md`'s multi-consumer model for that type.

No field anywhere in this module is capable of representing a modified
score, a modified risk/compliance verdict, a modified `CandidateTrade`,
or a new/re-derived execution instruction (ADR-007 §4's type-level
guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..scanner.models import Direction

SCHEMA_VERSION = 1


class Verdict(Enum):
    """The Execution Validator's binary output (ADR-007 §3, §4) — never
    graded, mirroring Compliance Engine's own APPROVE/BLOCK shape."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class CheckStatus(Enum):
    """Every check's individual result (ADR-007 §10) — not just the final
    verdict. `UNEVALUABLE` and `FAILED` both block (ADR-007 §8 Hard
    Rule); they are kept distinct only for audit clarity."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNEVALUABLE = "UNEVALUABLE"


@dataclass(frozen=True)
class CheckEvaluation:
    """One execution check's independent evaluation (ADR-007 §6). Every
    check is combined by AND — any single non-`PASSED` result blocks the
    whole decision (§6, mirroring `ADR-006` §5's all-must-pass model).

    `warning` is populated only on a `PASSED` result that is close to,
    but not over, a configured drift tolerance (spread/slippage) — an
    advisory note distinct from a blocking reason; it never affects
    `status` or the overall verdict.
    """

    check: str
    status: CheckStatus
    detail: str
    warning: Optional[str] = None

    @property
    def blocks(self) -> bool:
        return self.status != CheckStatus.PASSED


@dataclass(frozen=True)
class AccountState:
    """A fresh, at-this-instant read of account facts (ADR-007 §2) —
    scoped to exactly what this stage's checks need (equity drift,
    margin sufficiency). Any field left `None` means that specific input
    cannot be reliably read right now, and per ADR-007's Hard Rules, the
    corresponding check resolves to `UNEVALUABLE` — which blocks (§8),
    never a default PASSED."""

    equity: Optional[float]
    available_margin: Optional[float]


@dataclass(frozen=True)
class BrokerState:
    """A fresh, at-this-instant read of broker connection/tradability
    facts (ADR-007 §2). `symbol_tradable=None` means this specific fact
    could not be read right now — fails the corresponding check closed,
    never assumed tradable."""

    connected: bool
    symbol_tradable: Optional[bool]


@dataclass(frozen=True)
class ExecutionDecision:
    """One `ComplianceDecision`'s execution-readiness verdict (ADR-007
    §4). Immutable once produced; MT5 Bridge consumes it, never rewrites
    it — extending the chain `ScannerObservation` → `CandidateTrade` →
    `ScoreResult` → `RiskDecision` → `ComplianceDecision` →
    `ExecutionDecision`.

    `trace_id` and `candidate_id` are the propagated `RiskDecision`
    values verbatim (via `ComplianceDecision`), extending the trace chain
    established at every prior stage (ADR-007 §10).

    `blocking_reasons` is non-empty only on `REJECT` — the specific
    check(s) that failed or could not be evaluated. `reason_codes`
    mirrors `blocking_reasons` on `REJECT`, or names every passed check
    on `APPROVE` (ADR-007 §4: "confirmation of which checks passed").
    `warnings` collects every check's advisory note (see
    `CheckEvaluation.warning`) — never affects `verdict`.
    """

    schema_version: int
    trace_id: str
    candidate_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    timestamp: datetime
    direction: Direction
    verdict: Verdict
    blocking_reasons: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    warnings: Tuple[str, ...]
    check_evaluations: Tuple[CheckEvaluation, ...]
    execution_validator_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocking_reasons", tuple(self.blocking_reasons))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "check_evaluations", tuple(self.check_evaluations))
