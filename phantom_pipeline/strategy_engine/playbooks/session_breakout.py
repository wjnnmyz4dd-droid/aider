"""SESSION_BREAKOUT — reserved Strategy ID (ADR-003 §8).

Hypothesis category: a breakout of a prior session's range as a
directional trigger. Reserved as a placeholder only — **no hypothesis
logic, no thresholds, no implementation code**, per ADR-003 §8's explicit
scoping.
"""

from __future__ import annotations

from typing import Tuple

from ..config import StrategyEngineConfig
from ..models import CandidateTrade
from ..playbook import Playbook, PlaybookMetadata
from ...scanner.models import ScannerObservation, SCHEMA_VERSION


class SessionBreakoutPlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="SESSION_BREAKOUT",
        version="0.1.0-placeholder",
        description=(
            "Reserved: a breakout of a prior session's range as a "
            "directional trigger. Design and implementation are out of "
            "scope for ADR-003 Phase 1 (ADR-003 §8)."
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
