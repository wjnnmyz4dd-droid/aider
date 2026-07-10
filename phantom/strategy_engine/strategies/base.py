"""The `Strategy` interface (ADR-026 §1 "Strategy Qualification").

Every strategy must explicitly qualify itself before it can compete --
`qualify()` is the only entry point, and every concrete strategy checks
pair eligibility (via `eligibility.check_eligibility`) before any
regime-specific logic runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from phantom.evidence_engine.models import EvidenceSnapshot
from phantom.market_intelligence.models import MarketIntelligenceSnapshot

from ..config import StrategyEngineConfig
from ..models import QualificationResult, StrategyDefinition


class Strategy(ABC):
    @property
    @abstractmethod
    def definition(self) -> StrategyDefinition:
        ...

    @abstractmethod
    def qualify(
        self,
        pair: str,
        evidence: EvidenceSnapshot,
        market_intelligence: MarketIntelligenceSnapshot,
        config: StrategyEngineConfig,
    ) -> QualificationResult:
        ...


__all__ = ["Strategy"]
