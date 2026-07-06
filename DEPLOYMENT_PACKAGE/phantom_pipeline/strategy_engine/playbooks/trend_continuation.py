"""TREND_CONTINUATION — reserved Strategy ID (ADR-003 §8).

Hypothesis category: continuation of an already-established trend
following a pause or pullback. Reserved as a placeholder only — **no
hypothesis logic, no thresholds, no implementation code**, per ADR-003
§8's explicit scoping.
"""

from __future__ import annotations

from typing import Tuple

from ..config import StrategyEngineConfig
from ..models import CandidateTrade
from ..playbook import Playbook, PlaybookMetadata
from ...scanner.models import ScannerObservation, SCHEMA_VERSION


class TrendContinuationPlaybook(Playbook):
    _METADATA = PlaybookMetadata(
        strategy_id="TREND_CONTINUATION",
        version="0.1.0-placeholder",
        description=(
            "Reserved: continuation of an already-established trend "
            "following a pause or pullback. Design and implementation are "
            "out of scope for ADR-003 Phase 1 (ADR-003 §8)."
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
