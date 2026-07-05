"""Compliance Engine input/output objects (ADR-006 §2, §4).

`ComplianceDecision` is the Compliance Engine's sole output type: a
permit/deny verdict ("is this trade allowed"), never a sizing, scoring,
or execution instruction. Every input it consumes (`RiskDecision`,
`CandidateTrade`, `ScoreResult`, account state, broker/market state, news
state) is read-only — this module attaches a verdict alongside those
objects, it never rewrites them (ADR-006 §4, §19).

`AccountState`/`OpenPosition` here are Compliance Engine's own read-only
view of account state (ADR-006 §2) — a distinct, narrower concept from
`risk_engine.models.AccountState`, scoped to exactly what compliance
checks need (equity, balance, drawdown, and plain per-symbol/direction
position facts for position-count limits), not risk-budgeting fields
like `allocated_risk_percent` or `correlation_bucket`.

No field anywhere in this module is capable of representing a lot size,
a modified score, a modified `CandidateTrade` direction, an execution
instruction, or a position-management action (ADR-006 §4's type-level
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
    """The first stage in the pipeline whose output is legitimately a
    decision (ADR-006 §1) — not a fact, hypothesis, score, or budget."""

    APPROVE = "APPROVE"
    BLOCK = "BLOCK"


class CheckStatus(Enum):
    """Every check's individual result (ADR-006 §16) — not just the final
    verdict. `UNEVALUABLE` and `FAILED` both block (ADR-006 Hard Rules,
    §15); they are kept distinct only for audit clarity."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNEVALUABLE = "UNEVALUABLE"


@dataclass(frozen=True)
class CheckEvaluation:
    """One compliance check's independent evaluation (ADR-006 §5). Every
    check is combined by AND — any single non-`PASSED` result blocks the
    whole decision."""

    check: str
    status: CheckStatus
    detail: str

    @property
    def blocks(self) -> bool:
        return self.status != CheckStatus.PASSED


@dataclass(frozen=True)
class OpenPosition:
    """One currently open position (ADR-006 §2) — used only for the
    Maximum Positions check (§13); carries no risk-budgeting fields."""

    symbol: str
    direction: Direction


@dataclass(frozen=True)
class AccountState:
    """Account state (ADR-006 §2) — equity, balance, drawdown, and open
    positions. Any field left `None` means that specific input cannot be
    reliably evaluated, and per ADR-006's Hard Rules, every check that
    depends on it resolves to `UNEVALUABLE` — which blocks (§15), never a
    default APPROVE.

    `open_positions` is never `None` — an empty tuple is the (genuinely
    known) flat-account case, distinct from an unavailable feed.
    """

    equity: Optional[float]
    balance: Optional[float]
    daily_drawdown_pct: Optional[float]
    total_drawdown_pct: Optional[float]
    open_positions: Tuple[OpenPosition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_positions", tuple(self.open_positions))


@dataclass(frozen=True)
class NewsBlackoutWindow:
    """One high-impact news blackout window for a single currency
    (ADR-006 §8), sourced exclusively from the live MT5 Calendar."""

    currency: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class NewsCalendarState:
    """The live economic calendar's current state (ADR-006 §2, §8).
    `feed_stale=True` means the live calendar feed is stale or
    unavailable — per §8's Hard Rule, this fails the news check closed,
    never defaulting to "no news"."""

    feed_stale: bool
    blackout_windows: Tuple[NewsBlackoutWindow, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "blackout_windows", tuple(self.blackout_windows))


@dataclass(frozen=True)
class ComplianceDecision:
    """One `RiskDecision`'s compliance verdict (ADR-006 §4). Immutable
    once produced; Execution Validator attaches its own verdict alongside
    it, never rewrites it — extending the chain `ScannerObservation` →
    `CandidateTrade` → `ScoreResult` → `RiskDecision` → `ComplianceDecision`.

    `trace_id` and `candidate_id` are the propagated `RiskDecision` values
    verbatim, extending the trace chain established at every prior stage
    (ADR-006 §16).

    `blocking_rules` names every check that triggered (or failed to
    evaluate) a BLOCK; `reason_codes` mirrors `blocking_rules` on BLOCK,
    or names every passed check on APPROVE (ADR-006 §4: "confirmation of
    which checks passed for an APPROVE").
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
    blocking_rules: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    check_evaluations: Tuple[CheckEvaluation, ...]
    compliance_engine_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocking_rules", tuple(self.blocking_rules))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "check_evaluations", tuple(self.check_evaluations))
