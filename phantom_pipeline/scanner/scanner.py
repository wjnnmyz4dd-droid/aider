"""The Scanner (ADR-002).

`Scanner.scan()` is the single entry point (§7): given a symbol and its
current market-data snapshot, it returns exactly one `ScannerObservation`.
It is referentially transparent (§2) — the only state `Scanner` itself
holds is `self.config` (immutable) and an optional `self.metrics` sink,
neither of which feeds back into a call's output. Logging and metrics are
the only side effects (§7, §11, §12); both run after the observation is
fully built and never alter it.

Every structural/derived computation runs exactly once per scan and its
result is threaded through to every consumer that needs it (§13):
`atr()` is computed once inside `compute_volatility` and its
`atr_current` is reused by `swing_points` and `compute_structure`'s
order-block detection; `swing_points` is computed once and reused by
`compute_structure` and every Amendment 1 composite function; `trend.py`'s
strength history is computed once per timeframe and the primary
timeframe's history is reused by `trend_momentum`.

On any ADR-002 §9 failure mode, this returns a fully "unknown"
observation (§10) — never a partially-fabricated one.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Mapping, Optional, Sequence

from ..data_pipeline.models import MarketSnapshot, NormalizedBar
from ..data_pipeline.trace import make_trace_id
from . import composite, session as session_mod, structure as structure_mod, swing as swing_mod
from . import trend as trend_mod
from . import volatility as volatility_mod
from .config import DEFAULT_CONFIG, ScannerConfig
from .logging_sink import log_observation
from .metrics import ScannerMetrics
from .models import (
    SCHEMA_VERSION,
    DataQualityFlag,
    Direction,
    MarketPhase,
    RangeStructure,
    ScannerObservation,
    SessionState,
    StructureConfidence,
    StructureTrendState,
    SwingKind,
    SwingSequenceType,
    VolatilityLabel,
    VolatilityState,
)
from .quality import assess_quality


def _make_trace_id(
    symbol: str, primary_timeframe: str, session_time: datetime, primary_bars: Sequence[NormalizedBar]
) -> str:
    last_bar_fingerprint = primary_bars[-1].trace_id if primary_bars else "empty"
    return make_trace_id(
        "scan",
        symbol,
        primary_timeframe,
        session_time.isoformat(),
        str(len(primary_bars)),
        last_bar_fingerprint,
    )


def _unknown_observation(
    symbol: str,
    timestamp: datetime,
    trace_id: str,
    flag: DataQualityFlag,
    session_state: SessionState,
) -> ScannerObservation:
    return ScannerObservation(
        schema_version=SCHEMA_VERSION,
        trace_id=trace_id,
        symbol=symbol,
        timestamp=timestamp,
        trend={},
        structure=(),
        volatility=VolatilityState(label=VolatilityLabel.UNKNOWN, ratio=None),
        session=session_state,
        liquidity_events=(),
        data_quality_flag=flag,
        external_structure=StructureTrendState(Direction.UNKNOWN, SwingSequenceType.UNKNOWN),
        internal_structure=StructureTrendState(Direction.UNKNOWN, SwingSequenceType.UNKNOWN),
        swing_hierarchy=(),
        equal_highs=(),
        equal_lows=(),
        range_structure=RangeStructure.UNKNOWN,
        phase=MarketPhase.UNKNOWN,
        trend_acceleration=None,
        trend_exhaustion=None,
        structure_confidence=StructureConfidence.UNKNOWN,
    )


class Scanner:
    """Stateless-in-spirit: `config` is frozen, `metrics` (if supplied) is
    a write-only sink whose contents never feed back into a scan's
    output — the Scanner Purity Principle (§2) is upheld by construction,
    not by convention."""

    def __init__(self, config: ScannerConfig = DEFAULT_CONFIG, metrics: Optional[ScannerMetrics] = None):
        self.config = config
        self.metrics = metrics

    def scan(
        self,
        symbol: str,
        bars_by_timeframe: Mapping[str, Sequence[NormalizedBar]],
        market_snapshot: Optional[MarketSnapshot],
        session_time: datetime,
        primary_timeframe: str,
    ) -> ScannerObservation:
        start = time.monotonic()
        observation = self._scan(
            symbol, bars_by_timeframe, market_snapshot, session_time, primary_timeframe
        )
        latency = time.monotonic() - start

        log_observation(observation, level=self.config.log_level)
        if self.metrics is not None:
            self.metrics.record_observation(observation, latency_seconds=latency)

        return observation

    def _scan(
        self,
        symbol: str,
        bars_by_timeframe: Mapping[str, Sequence[NormalizedBar]],
        market_snapshot: Optional[MarketSnapshot],
        session_time: datetime,
        primary_timeframe: str,
    ) -> ScannerObservation:
        primary_bars = tuple(bars_by_timeframe.get(primary_timeframe, ()))
        trace_id = _make_trace_id(symbol, primary_timeframe, session_time, primary_bars)
        session_state = session_mod.compute_session(session_time, self.config)

        flag = assess_quality(
            symbol, bars_by_timeframe, market_snapshot, session_time, primary_timeframe, self.config
        )
        if flag != DataQualityFlag.NOMINAL:
            return _unknown_observation(symbol, session_time, trace_id, flag, session_state)

        trend_map = {}
        primary_strength_history: Sequence[float] = ()
        for timeframe, bars in bars_by_timeframe.items():
            computation = trend_mod.compute_trend(bars, self.config)
            trend_map[timeframe] = computation.reading
            if timeframe == primary_timeframe:
                primary_strength_history = computation.strength_history

        volatility_computation = volatility_mod.compute_volatility(primary_bars, self.config)

        swings = swing_mod.swing_points(primary_bars, self.config, volatility_computation.atr_current)

        structural_signals, liquidity_events = structure_mod.compute_structure(
            primary_bars, swings, volatility_computation.atr_current, self.config
        )

        external, internal = composite.external_internal_structure(swings)
        equal_highs = composite.equal_levels(
            structure_mod.major_swings(swings), SwingKind.HIGH, self.config.equal_level_tolerance_pct
        )
        equal_lows = composite.equal_levels(
            structure_mod.major_swings(swings), SwingKind.LOW, self.config.equal_level_tolerance_pct
        )
        range_state = composite.range_structure(volatility_computation.state.ratio, self.config)
        phase = composite.market_phase(external, internal, range_state)
        accelerating, exhausting = composite.trend_momentum(primary_strength_history)
        confidence = composite.structure_confidence(swings, external, internal, self.config)

        return ScannerObservation(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timestamp=session_time,
            trend=trend_map,
            structure=structural_signals,
            volatility=volatility_computation.state,
            session=session_state,
            liquidity_events=liquidity_events,
            data_quality_flag=flag,
            external_structure=external,
            internal_structure=internal,
            swing_hierarchy=swings,
            equal_highs=equal_highs,
            equal_lows=equal_lows,
            range_structure=range_state,
            phase=phase,
            trend_acceleration=accelerating,
            trend_exhaustion=exhausting,
            structure_confidence=confidence,
        )
