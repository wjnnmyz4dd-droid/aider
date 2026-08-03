"""Risk Engine input/output objects (ADR-005 §2, §4).

`RiskDecision` is the Risk Engine's sole output type: a capital-budgeting
answer ("how much"), never a decision about whether to act. There is no
separate failure-record type — per ADR-005 §3, a candidate the engine
cannot evaluate still receives a `RiskDecision`, with zero risk and an
explicit reason; the fail-closed path and the happy path share one type.

`AccountState`/`OpenPosition` are the Risk Engine's own read-only view of
account/risk state (ADR-005 §2) — not owned or produced by any other
stage.

No field anywhere in this module is capable of representing a compliance
verdict, an execution instruction, an MT5 instruction, or a position-
management action (ADR-005 §4's type-level guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..scanner.models import Direction

SCHEMA_VERSION = 1


class RiskTier(Enum):
    """A qualitative label describing which regime of capital allocation
    applied (ADR-005 §4) — never a numeric score. `NORMAL` means no
    constraint reduced risk below the per-trade ceiling; `DEFENSIVE` means
    at least one constraint reduced it below the ceiling but above zero;
    `HALTED` means the awarded risk is zero."""

    NORMAL = "NORMAL"
    DEFENSIVE = "DEFENSIVE"
    HALTED = "HALTED"


@dataclass(frozen=True)
class OpenPosition:
    """One currently open position, as tracked by account/risk state
    (ADR-005 §2) — used for portfolio heat, currency exposure, and
    correlation exposure (§9-§11)."""

    symbol: str
    direction: Direction
    allocated_risk_percent: float
    correlation_bucket: Optional[str]


@dataclass(frozen=True)
class AccountState:
    """Account/risk state (ADR-005 §2) — equity, drawdown, rolling
    trade-outcome history, and open positions. Any field left `None`
    means that specific input cannot be reliably evaluated, and per
    ADR-005's Hard Rules, the corresponding constraint resolves to zero
    risk (§15) — never guessed, never defaulted to a non-zero fallback.

    `open_positions` is never `None` — an empty tuple is the (genuinely
    known) flat-account case, distinct from an unavailable feed.
    """

    equity: Optional[float]
    daily_drawdown_pct: Optional[float]
    total_drawdown_pct: Optional[float]
    consecutive_losses: Optional[int]
    daily_risk_allocated_pct: Optional[float]
    open_positions: Tuple[OpenPosition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_positions", tuple(self.open_positions))


@dataclass(frozen=True)
class ConstraintEvaluation:
    """One risk constraint's independent evaluation (ADR-005 §6). The
    engine takes the minimum `allowed_risk_percent` across every
    `ConstraintEvaluation` it computes — never a pick of one constraint
    over another. `binding` is set by the engine after all constraints
    are computed, marking every constraint tied for that minimum."""

    constraint: str
    allowed_risk_percent: float
    binding: bool
    detail: str


@dataclass(frozen=True)
class RiskDecision:
    """One `ScoreResult`'s risk budget (ADR-005 §4). Immutable once
    produced; later stages (Compliance Engine, Execution Validator)
    attach their own verdicts alongside it, never rewrite it.

    `trace_id` and `candidate_id` are the propagated `ScoreResult` values
    verbatim, extending the trace chain from Scanner through Strategy
    Engine and Scoring Engine into risk budgeting (ADR-005 §16).

    `lot_size` is `None` whenever no `stop_distance` was supplied to
    `RiskEngine.decide()` — position-sizing conversion requires a price
    reference neither `ScannerObservation` nor `CandidateTrade` carries
    today (a known limitation, not a defect of this stage; see the
    Phase 1 deliverable report). The risk *budget* itself
    (`approved_risk_percent`/`approved_risk_amount`) never depends on
    `stop_distance` being supplied — sizing is a downstream unit
    conversion of the budget, not the budget itself.
    """

    schema_version: int
    trace_id: str
    candidate_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    timestamp: datetime
    direction: Direction
    approved_risk_percent: float
    approved_risk_amount: float
    lot_size: Optional[float]
    risk_tier: RiskTier
    limiting_constraint: str
    constraint_evaluations: Tuple[ConstraintEvaluation, ...]
    reason_codes: Tuple[str, ...]
    risk_engine_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "constraint_evaluations", tuple(self.constraint_evaluations)
        )
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
