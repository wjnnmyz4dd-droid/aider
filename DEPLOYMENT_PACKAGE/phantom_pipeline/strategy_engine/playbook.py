"""The playbook plugin interface (ADR-003 §5).

Every playbook is a new module implementing this interface plus a
`playbooks/` package entry (`registry.py`'s auto-discovery) — zero lines
changed in the engine's own code or any other playbook (ADR-003 §17).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from ..scanner.models import ScannerObservation
from .config import StrategyEngineConfig
from .models import CandidateTrade


class HealthStatus(Enum):
    """A playbook's own queryable status (ADR-003 §5), independent of any
    single call's outcome."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class PlaybookMetadata:
    """The plugin interface's declared identity (ADR-003 §5).

    `supported_symbols`/`supported_timeframes` are explicit tuples — an
    empty tuple means "supports none yet" (the honest declaration for an
    unimplemented placeholder), never an implicit "supports everything."
    A playbook must never silently run against a symbol/timeframe it
    wasn't designed for (§5).
    """

    strategy_id: str
    version: str
    description: str
    supported_symbols: Tuple[str, ...]
    supported_timeframes: Tuple[str, ...]
    schema_versions_supported: Tuple[int, ...]


class Playbook(ABC):
    """A single, independent hypothesis generator (ADR-003 §2, §5).

    Must be deterministic, stateless, and pure: `evaluate()` is a
    function of its declared inputs (`observation`, `config`) only —
    never module-level state, never randomness, never a cached prior
    result."""

    @property
    @abstractmethod
    def metadata(self) -> PlaybookMetadata:
        ...

    @abstractmethod
    def evaluate(
        self, observation: ScannerObservation, config: StrategyEngineConfig
    ) -> Tuple[CandidateTrade, ...]:
        """Return zero or more `CandidateTrade` hypotheses for `observation`.

        Must never raise for a condition the playbook can anticipate
        (missing/degraded required input) — that is an abstention (return
        `()`), not an exception. An exception here is reserved for a true
        implementation bug and is caught, logged, and isolated by the
        engine (ADR-003 §10), never propagated to another playbook."""
        ...

    def health_status(self, config: StrategyEngineConfig) -> HealthStatus:
        """Default: healthy whenever configuration marks this playbook
        enabled, disabled otherwise. A playbook may override this for a
        more specific operational signal (ADR-003 §5), but must never let
        a single call's outcome affect it (health is call-independent)."""
        return (
            HealthStatus.HEALTHY
            if config.is_enabled(self.metadata.strategy_id)
            else HealthStatus.DISABLED
        )
