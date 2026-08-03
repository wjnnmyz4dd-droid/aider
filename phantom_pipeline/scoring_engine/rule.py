"""The scoring rule plugin interface (ADR-004 §5, §15).

Every rule is a new module implementing this interface plus a `rules/`
package entry (`registry.py`'s auto-discovery) — zero lines changed in
the engine's own code or any other rule, mirroring the Strategy
Registry's extensibility guarantee (ADR-003 §17) one layer down.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..strategy_engine.models import CandidateTrade
from .config import ScoringEngineConfig
from .models import RuleContribution


@dataclass(frozen=True)
class ScoringRuleMetadata:
    """The plugin interface's declared identity (ADR-004 §5).

    `factor` names the factor-breakdown category this rule's
    contribution is grouped under (e.g. "evidence_strength",
    "directional_clarity") — the engine derives `FactorBreakdown` by
    grouping already-computed `RuleContribution`s by this field, never a
    second independent computation."""

    rule_id: str
    version: str
    description: str
    factor: str


class ScoringRule(ABC):
    """A single, independent scoring rule (ADR-004 §2, §5).

    Must be deterministic, stateless, and pure: `evaluate()` is a
    function of its declared inputs (`candidate`, `weight`) only — never
    module-level state, never randomness, never a cached prior result.
    """

    @property
    @abstractmethod
    def metadata(self) -> ScoringRuleMetadata:
        ...

    @abstractmethod
    def evaluate(self, candidate: CandidateTrade, config: ScoringEngineConfig) -> RuleContribution:
        """Return this rule's contribution for `candidate`. The rule reads
        its own weight via `config.weight_for(self.metadata.rule_id)` —
        and any other tunable parameter it needs from `config` — never a
        hardcoded value (ADR-004 §5). Mirrors `Playbook.evaluate()`
        receiving the whole `StrategyEngineConfig` (ADR-003 §5).

        Must never raise for a condition the rule can anticipate
        (missing/degraded required evidence) — that is an abstention
        (`RuleContribution` with `outcome=ABSTAINED`, `points=0.0`), not
        an exception. An exception here is reserved for a true
        implementation bug and is caught, logged, and isolated by the
        engine (ADR-004 §8), never propagated to another rule or
        candidate."""
        ...
