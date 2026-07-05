"""Replay data production (ADR-013 §10).

`ReplayRecorder` captures the exact ticks/bars a live (or historical)
run produced. `replay_through` re-feeds a captured `ReplaySeries`'
ticks through a fresh `DataPipeline` instance, using the same ingestion
path live data uses — never a separate code path — so replay exercises
the same normalization/validation logic live data does (ADR-013 §10).

Replay never modifies live data: a `ReplaySeries` is an immutable
snapshot: consuming it never mutates the recorder or any other stage's
state.

Capture is bounded: `ReplayRecorder` holds at most
`config.replay_max_ticks_per_symbol` ticks and
`config.replay_max_bars_per_symbol` bars per symbol, evicting the
oldest entry first (deterministic FIFO via a fixed-size deque) once
that bound is reached — the same bounded/TTL-pruned discipline every
other stateful component in this package already follows (`ADR-002`
§2's session clock; `HistoricalCache` in historical.py).
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List

from .config import PipelineConfig
from .models import NormalizedBar, NormalizedTick, ReplaySeries, SCHEMA_VERSION
from .trace import make_trace_id


class ReplayRecorder:
    """Captures ticks and finalized bars for one symbol as they are produced,
    bounded by `config.replay_max_ticks_per_symbol` /
    `replay_max_bars_per_symbol`."""

    def __init__(self, symbol: str, config: PipelineConfig):
        self.symbol = symbol
        self._ticks: Deque[NormalizedTick] = deque(
            maxlen=config.replay_max_ticks_per_symbol
        )
        self._bars: Deque[NormalizedBar] = deque(
            maxlen=config.replay_max_bars_per_symbol
        )

    def record_tick(self, tick: NormalizedTick) -> None:
        if tick.symbol != self.symbol:
            return
        self._ticks.append(tick)

    def record_bar(self, bar: NormalizedBar) -> None:
        if bar.symbol != self.symbol:
            return
        self._bars.append(bar)

    def to_replay_series(self) -> ReplaySeries:
        trace_id = make_trace_id(
            "replay",
            self.symbol,
            str(len(self._ticks)),
            str(len(self._bars)),
        )
        return ReplaySeries(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=self.symbol,
            ticks=tuple(self._ticks),
            bars=tuple(self._bars),
        )


def is_replay_ready(replay_series: ReplaySeries) -> bool:
    """Whether `replay_series` currently holds enough captured data to
    support a meaningful replay run (ADR-013 §15's "Replay readiness"
    metric) — at least one captured tick and one finalized bar. A purely
    descriptive check of already-captured state; never itself captures or
    fabricates anything."""
    return bool(replay_series.ticks) and bool(replay_series.bars)


def replay_through(replay_series: ReplaySeries, pipeline) -> List[NormalizedBar]:
    """Re-feed a captured `ReplaySeries`' ticks through `pipeline` (a fresh
    `DataPipeline` instance) via its normal ingestion path, returning the
    bars produced. Never modifies `replay_series` itself."""
    produced: List[NormalizedBar] = []
    for tick in replay_series.ticks:
        bars = pipeline.process_raw_tick(
            raw_symbol=tick.symbol,
            raw_timestamp=tick.timestamp,
            bid=tick.bid,
            ask=tick.ask,
            last=tick.last,
            volume=tick.volume,
            source=tick.source,
        )
        produced.extend(bars)
    return produced
