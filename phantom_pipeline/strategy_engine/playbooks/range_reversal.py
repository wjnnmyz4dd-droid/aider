"""RANGE_REVERSAL — reserved Strategy ID (ADR-003 §8).

Hypothesis category: rejection at the boundary of an established trading
range. Reserved as a placeholder only — **no hypothesis logic, no
thresholds, no implementation code**, per ADR-003 §8's explicit scoping.
"""

from __future__ import annotations

from typing import Tuple

from ..config import StrategyEngineConfig
from ..models import CandidateTrade
from ..playbook import Playbook, PlaybookMetadata
from ...scanner.models import ScannerObservation, SCHEMA_VERSION


class RangeReversalPlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="RANGE_REVERSAL",
        version="0.1.0-placeholder",
        description=(
            "Reserved: rejection at the boundary of an established "
            "trading range. Design and implementation are out of scope "
            "for ADR-003 Phase 1 (ADR-003 §8)."
        ),
        supported_symbols=(),
        supported_timeframes=(),
        schema_versions_supported=(SCHEMA_VERSION,),
    )

    @property
    def metadata(self) -> PlaybookMetadata:
        return self._METADATA

    def evaluate(
        self, observation: ScannerObservation, config: StrategyEngineConfig
    ) -> Tuple[CandidateTrade, ...]:
        return ()
