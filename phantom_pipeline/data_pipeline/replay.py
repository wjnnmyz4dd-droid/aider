"""Replay data production (ADR-013 §10).

`ReplayRecorder` captures the exact ticks/bars a live (or historical)
run produced. `replay_through` re-feeds a captured `ReplaySeries`'
ticks through a fresh `DataPipeline` instance, using the same ingestion
path live data uses — never a separate code path — so replay exercises
the same normalization/validation logic live data does (ADR-013 §10).

Replay never modifies live data: a `ReplaySeries` is an immutable
snapshot: consuming it never mutates the recorder or any other stage's
state.
"""

from __future__ import annotations

from typing import List

from .models import NormalizedBar, NormalizedTick, ReplaySeries, SCHEMA_VERSION
from .trace import make_trace_id


class ReplayRecorder:
    """Captures ticks and finalized bars for one symbol as they are produced."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._ticks: List[NormalizedTick] = []
        self._bars: List[NormalizedBar] = []

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
