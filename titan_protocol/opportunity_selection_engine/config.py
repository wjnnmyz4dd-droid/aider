"""Configuration for the Opportunity Selection Engine (ADR-037 §8/§11).

Every tuning parameter this package owns is named here -- no magic
numbers in `selection.py`/`store.py`/`engine.py` (CLAUDE.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from titan_protocol.strategy_engine.models import SessionName

OPPORTUNITY_SELECTION_ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class EnabledOpportunityWindow:
    """One entry in the enabled-sessions configuration surface (ADR-037
    §8, revised): `anchor_hour_utc`/`anchor_minute_utc` are the real
    identity reference into Gate B's `opening_range_anchors` -- not
    `session_name`, which is carried through only as a descriptive/
    observability field, never part of any key (ADR-037 §8's explicit
    "references one specific configured anchor entry, not merely a
    `SessionName` label" requirement)."""

    session_name: SessionName
    anchor_hour_utc: int
    anchor_minute_utc: int
    enabled: bool = True


@dataclass(frozen=True)
class OpportunitySelectionEngineConfig:
    """`enabled_windows` defaults to `()` -- the architecturally-required
    degenerate/inert case (ADR-037 §2's configurable-cardinality
    requirement). `tie_tolerance` is this engine's own field, never
    literally shared with `StrategyEngineConfig.score_tie_tolerance` --
    reusing a field across two unrelated engines would itself be a new,
    unjustified cross-engine coupling (ADR-037 §6, product-policy
    decision: `0.5`). `cross_pair_selection_enabled` is the explicit,
    operator-set intent flag (ADR-037 §11 item 3) that replaces a
    Gate-A-pair-count heuristic entirely -- defaults to `False`, so any
    deployment that never touches this field remains entirely inert with
    respect to every structural-readiness invariant, regardless of Gate
    A's actual width."""

    enabled_windows: Tuple[EnabledOpportunityWindow, ...] = ()
    tie_tolerance: float = 0.5
    cross_pair_selection_enabled: bool = False

    def __post_init__(self) -> None:
        if self.tie_tolerance < 0.0:
            raise ValueError(f"tie_tolerance must be >= 0.0, got {self.tie_tolerance}")
        seen: set = set()
        for window in self.enabled_windows:
            key = (window.anchor_hour_utc, window.anchor_minute_utc)
            if key in seen:
                raise ValueError(
                    f"enabled_windows contains more than one entry for anchor {key} -- "
                    f"each (anchor_hour_utc, anchor_minute_utc) pair must be unique"
                )
            seen.add(key)


__all__ = [
    "OPPORTUNITY_SELECTION_ENGINE_VERSION",
    "EnabledOpportunityWindow",
    "OpportunitySelectionEngineConfig",
]
