"""The Strategy Engine (ADR-003).

`StrategyEngine.generate()` is the single entry point: given one
`ScannerObservation` and the timeframe it was scanned for, return zero or
more `CandidateTrade` hypotheses. **It never resolves conflicts** — every
valid candidate from every enabled, applicable playbook is forwarded
unmodified (ADR-003 §9); the engine itself never picks a winner.

A non-nominal `data_quality_flag` is an automatic no-hypothesis condition
for the entire call (ADR-002 §10's contract, honored here per ADR-003
§4) — no playbook is even invoked. Each playbook is then independently
gated (enabled, schema-version-compatible, symbol/timeframe-supported)
and invoked inside a try/except: an exception is caught, logged, and
isolated at the playbook boundary (ADR-003 §10) — it never propagates to
crash the engine or affect any other playbook's output in the same call.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..scanner.models import DataQualityFlag, ScannerObservation
from .config import DEFAULT_CONFIG, StrategyEngineConfig
from .logging_sink import log_candidate_trade, log_playbook_abstention, log_playbook_failure
from .metrics import StrategyEngineMetrics
from .models import CandidateTrade
from .registry import StrategyRegistry


class StrategyEngine:
    def __init__(
        self,
        registry: StrategyRegistry,
        config: StrategyEngineConfig = DEFAULT_CONFIG,
        metrics: Optional[StrategyEngineMetrics] = None,
    ):
        self.registry = registry
        self.config = config
        self.metrics = metrics

    def generate(
        self, observation: ScannerObservation, primary_timeframe: str
    ) -> Tuple[CandidateTrade, ...]:
        if observation.data_quality_flag != DataQualityFlag.NOMINAL:
            return ()

        candidates: List[CandidateTrade] = []

        for playbook in self.registry.playbooks:
            strategy_id = playbook.metadata.strategy_id

            if not self._is_applicable(playbook, observation, primary_timeframe):
                continue

            try:
                produced = playbook.evaluate(observation, self.config)
            except Exception as exc:
                log_playbook_failure(
                    strategy_id, playbook.metadata.version, observation.trace_id, exc
                )
                if self.metrics is not None:
                    self.metrics.record_failure(strategy_id)
                continue

            if not produced:
                log_playbook_abstention(strategy_id, "no_hypothesis", observation.trace_id)
                if self.metrics is not None:
                    self.metrics.record_abstention(strategy_id)
                continue

            for candidate in produced:
                log_candidate_trade(candidate)
                if self.metrics is not None:
                    self.metrics.record_candidate(candidate)
            candidates.extend(produced)

        return tuple(candidates)

    def _is_applicable(self, playbook, observation: ScannerObservation, primary_timeframe: str) -> bool:
        strategy_id = playbook.metadata.strategy_id
        metadata = playbook.metadata

        if not self.config.is_enabled(strategy_id):
            log_playbook_abstention(strategy_id, "disabled", observation.trace_id)
            if self.metrics is not None:
                self.metrics.record_abstention(strategy_id)
            return False

        if observation.schema_version not in metadata.schema_versions_supported:
            log_playbook_abstention(
                strategy_id, "unsupported_schema_version", observation.trace_id
            )
            if self.metrics is not None:
                self.metrics.record_abstention(strategy_id)
            return False

        if metadata.supported_symbols and observation.symbol not in metadata.supported_symbols:
            log_playbook_abstention(strategy_id, "unsupported_symbol", observation.trace_id)
            if self.metrics is not None:
                self.metrics.record_abstention(strategy_id)
            return False

        if primary_timeframe not in metadata.supported_timeframes:
            log_playbook_abstention(strategy_id, "unsupported_timeframe", observation.trace_id)
            if self.metrics is not None:
                self.metrics.record_abstention(strategy_id)
            return False

        return True
