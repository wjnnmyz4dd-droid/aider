"""Versioned configuration for the Compliance Engine (ADR-006 §5).

Every threshold/window/limit here is a tunable implementation default,
never architecture (`CLAUDE.md` §7, §3) — the same discipline every
prior stage's config module already established. Rules themselves are
hard policy (ADR-006 §5): a check either passes or it doesn't, but the
specific numbers are configuration, versioned like every other stage's.

Symbols absent from `spread_thresholds`/`slippage_thresholds` are
unevaluable, not assumed safe — the same fail-closed treatment
`risk_engine.config`'s `correlation_buckets` already established for an
unconfigured symbol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Tuple

COMPLIANCE_ENGINE_VERSION = "1.0.0-phase1"


@dataclass(frozen=True)
class SessionWindow:
    """A named session's daily time-of-day window, in UTC-of-day terms
    (hour, minute), inclusive start, exclusive end (ADR-006 §9). Does not
    itself handle daylight-saving transitions — the same known
    limitation `scanner.config.SessionWindow` already documents."""

    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int


@dataclass(frozen=True)
class ComplianceEngineConfig:
    """`spread_thresholds`/`slippage_thresholds` map `symbol` -> a maximum
    allowed value (price units). A symbol absent from either mapping has
    an unevaluable threshold — per ADR-006 §11/§12's Hard Rule, this
    fails the corresponding check closed, never assumed safe. The empty
    defaults mean every symbol is unevaluable until the deployer
    configures thresholds.

    `session_windows` defaults to the same four-session placeholder set
    `scanner.config.SessionWindow` uses (Sydney/Tokyo/London/New York,
    covering nearly the full UTC day) — a sensible non-blocking Phase 1
    default, not architecture. An empty `session_windows` tuple means the
    session check is unconfigured and therefore unevaluable (fails
    closed), not "no restriction."
    """

    max_daily_drawdown_percent: float = 3.0
    max_total_drawdown_percent: float = 8.0
    max_positions_per_symbol: int = 3
    max_positions_account_wide: int = 6
    session_windows: Tuple[SessionWindow, ...] = (
        SessionWindow("SYDNEY", 21, 0, 6, 0),
        SessionWindow("TOKYO", 0, 0, 9, 0),
        SessionWindow("LONDON", 7, 0, 16, 0),
        SessionWindow("NEW_YORK", 12, 0, 21, 0),
    )
    spread_thresholds: Mapping[str, float] = field(default_factory=dict)
    slippage_thresholds: Mapping[str, float] = field(default_factory=dict)
    log_level: int = 20  # logging.INFO, without importing logging here

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_windows", tuple(self.session_windows))
        object.__setattr__(
            self, "spread_thresholds", MappingProxyType(dict(self.spread_thresholds))
        )
        object.__setattr__(
            self, "slippage_thresholds", MappingProxyType(dict(self.slippage_thresholds))
        )

    def spread_threshold_for(self, symbol: str):
        return self.spread_thresholds.get(symbol)

    def slippage_threshold_for(self, symbol: str):
        return self.slippage_thresholds.get(symbol)


DEFAULT_CONFIG = ComplianceEngineConfig()
