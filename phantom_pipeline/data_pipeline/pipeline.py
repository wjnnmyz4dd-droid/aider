"""DataPipeline — the Data Pipeline stage's public entry point (ADR-013).

Orchestrates ingestion, normalization, base-timeframe bar construction,
gap detection, data quality assessment, health reporting, historical
caching, and replay capture. Everything here is deterministic given an
identical sequence of raw ticks and configuration (ADR-013 Hard Rules).

Multi-timeframe bars are derived on demand from the base-timeframe
historical cache via `aggregate_bars` — never recomputed independently
from ticks per timeframe (ADR-013 §2's "compute once, share the
result" discipline).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from .bars import BarBuilder, aggregate_bars
from .config import PipelineConfig, DEFAULT_CONFIG
from .gaps import repair_gaps
from .historical import HistoricalCache
from .ingest import TickIngestor
from .metrics import DataPipelineMetrics
from .models import (
    DataQualityReport,
    HistoricalSeries,
    MarketSnapshot,
    NormalizedBar,
    PipelineHealth,
    SCHEMA_VERSION,
    tick_price,
)
from .quality import compute_quality_report
from .health import compute_pipeline_health
from .logging_sink import log_cache_invalidation, log_gap_repair, log_ingestion_event
from .replay import ReplayRecorder, is_replay_ready
from .trace import make_trace_id


class DataPipeline:
    """The Data Pipeline stage: the sole producer of normalized market data."""

    def __init__(
        self,
        config: PipelineConfig = DEFAULT_CONFIG,
        base_timeframe: str = "M1",
        metrics: Optional[DataPipelineMetrics] = None,
    ):
        self.config = config
        self.base_timeframe = base_timeframe
        self.metrics = metrics
        self._ingestor = TickIngestor(config)
        self._bar_builder = BarBuilder(config, base_timeframe)
        self._cache = HistoricalCache(config)
        self._recorders: Dict[str, ReplayRecorder] = {}
        self._latest_snapshot: Dict[str, MarketSnapshot] = {}
        self.ticks_processed = 0
        self.bars_produced = 0
        self.gap_repair_count = 0

    def _recorder_for(self, symbol: str) -> ReplayRecorder:
        recorder = self._recorders.get(symbol)
        if recorder is None:
            recorder = ReplayRecorder(symbol, self.config)
            self._recorders[symbol] = recorder
        return recorder

    def process_raw_tick(
        self,
        raw_symbol: str,
        raw_timestamp: datetime,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        last: Optional[float] = None,
        volume: Optional[float] = None,
        source: str = "unknown",
        market_status: str = "OPEN",
    ) -> List[NormalizedBar]:
        """Ingest one raw tick; returns any base-timeframe bar(s) finalized
        by it (usually zero or one)."""
        result = self._ingestor.ingest(
            raw_symbol, raw_timestamp, bid, ask, last, volume, source
        )
        if self.metrics is not None:
            if result.duplicate:
                self.metrics.record_duplicate_tick()
            if result.out_of_order_dropped:
                self.metrics.record_out_of_order_tick()
            if result.malformed_reason is not None:
                self.metrics.record_dropped_tick()
        if result.tick is None:
            return []

        tick = result.tick
        self.ticks_processed += 1
        self._recorder_for(tick.symbol).record_tick(tick)
        log_ingestion_event(tick, level=self.config.log_level)

        price = tick_price(tick)
        spread = (
            (tick.ask - tick.bid)
            if tick.bid is not None and tick.ask is not None
            else 0.0
        )
        if price is not None:
            snapshot_trace_id = make_trace_id(
                "snapshot", tick.symbol, tick.timestamp.isoformat()
            )
            self._latest_snapshot[tick.symbol] = MarketSnapshot(
                schema_version=SCHEMA_VERSION,
                trace_id=snapshot_trace_id,
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                price=price,
                spread=spread,
                market_status=market_status,
            )

        finalized = self._bar_builder.add_tick(tick)
        produced: List[NormalizedBar] = []
        if finalized is not None:
            self._cache.add_bar(finalized)
            self._recorder_for(finalized.symbol).record_bar(finalized)
            self.bars_produced += 1
            log_ingestion_event(finalized, level=self.config.log_level)
            produced.append(finalized)
        return produced

    def flush(self, symbol: str) -> Optional[NormalizedBar]:
        """Finalize any in-progress base bar for `symbol` (e.g. at session
        end); returns it if one existed."""
        bar = self._bar_builder.flush(symbol)
        if bar is not None:
            self._cache.add_bar(bar)
            self._recorder_for(bar.symbol).record_bar(bar)
            self.bars_produced += 1
            log_ingestion_event(bar, level=self.config.log_level)
        return bar

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        return self._latest_snapshot.get(symbol)

    def get_historical_series(self, symbol: str, timeframe: str) -> HistoricalSeries:
        """Return the base-timeframe series directly, or an aggregated
        higher-timeframe series derived from it (never re-derived from
        ticks)."""
        if timeframe == self.base_timeframe:
            series = self._cache.get_series(symbol, timeframe)
            if self.metrics is not None:
                self.metrics.record_cache_access(hit=bool(series.bars))
            return series

        base_series = self._cache.get_series(symbol, self.base_timeframe)
        if self.metrics is not None:
            self.metrics.record_cache_access(hit=bool(base_series.bars))
        aggregated = aggregate_bars(base_series.bars, timeframe, self.config)
        trace_id = make_trace_id(
            "historical",
            symbol,
            timeframe,
            aggregated[0].timestamp.isoformat() if aggregated else "empty",
            aggregated[-1].timestamp.isoformat() if aggregated else "empty",
        )
        return HistoricalSeries(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timeframe=timeframe,
            bars=tuple(aggregated),
        )

    def get_historical_series_repaired(self, symbol: str, timeframe: str) -> HistoricalSeries:
        """`get_historical_series`'s bounded, single-bar-only repair
        counterpart (ADR-013 §7) — a separate, explicitly-invoked method,
        never applied automatically, so a caller that wants the raw,
        unrepaired series (e.g. `get_quality_report`, which must see the
        genuine gap to report it) is never surprised by a silently
        different result from the same call it already makes."""
        series = self.get_historical_series(symbol, timeframe)
        repaired_bars = repair_gaps(series.bars, self.config)
        repaired_count = len(repaired_bars) - len(series.bars)
        if repaired_count > 0:
            self.gap_repair_count += repaired_count
            if self.metrics is not None:
                self.metrics.record_gap_repaired(repaired_count)
            for bar in repaired_bars:
                if bar.is_repaired:
                    log_gap_repair(bar, level=self.config.log_level)

        trace_id = make_trace_id(
            "historical_repaired",
            symbol,
            timeframe,
            repaired_bars[0].timestamp.isoformat() if repaired_bars else "empty",
            repaired_bars[-1].timestamp.isoformat() if repaired_bars else "empty",
        )
        return HistoricalSeries(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timeframe=timeframe,
            bars=tuple(repaired_bars),
        )

    def load_historical_bars(self, symbol: str, timeframe: str, bars: Sequence[NormalizedBar]) -> None:
        """Bulk-load a symbol/timeframe's history directly into the
        historical cache (ADR-013 §4's "Historical Data" input, §11's
        warm-cache bootstrap) — never through tick ingestion, and never
        captured into `ReplayRecorder`: this is pre-existing history, not
        a live-produced event, so replay determinism for genuinely
        live-produced data is unaffected. Deterministic: loading the same
        `bars` twice produces the same resulting cached series both times.
        """
        self._cache.load_bulk(symbol, timeframe, bars)

    def warm_start(self, series: Sequence[HistoricalSeries]) -> None:
        """Bootstrap the historical cache for many symbol/timeframe pairs
        at once (ADR-013 §11's "Warm cache... avoiding a cold-start
        warm-up gap for every symbol simultaneously"). Each entry in
        `series` is loaded via `load_historical_bars`; a symbol/timeframe
        never warm-started here simply starts cold, passing through
        `ADR-002` §9's own warm-up failure mode until enough live history
        accumulates — no special-cased behavior is needed for that case."""
        for one_series in series:
            self.load_historical_bars(one_series.symbol, one_series.timeframe, one_series.bars)

    def invalidate_cache(self, symbol: str, timeframe: str, reason: str, now: datetime) -> int:
        """Explicitly invalidate a symbol/timeframe's cached series
        (ADR-013 §11) — e.g. a detected vendor data revision or a
        configuration change to a symbol's timeframe set. Never a silent
        clear: always logs a complete, attributable event. Returns the
        number of bars removed."""
        bars_cleared = self._cache.invalidate(symbol, timeframe)
        log_cache_invalidation(symbol, timeframe, reason, bars_cleared, now)
        return bars_cleared

    def get_quality_report(
        self,
        symbol: str,
        timeframe: str,
        window_start: datetime,
        window_end: datetime,
        now: datetime,
    ) -> DataQualityReport:
        series = self.get_historical_series(symbol, timeframe)
        bars_in_window = [
            b for b in series.bars if window_start <= b.timestamp <= window_end
        ]
        report = compute_quality_report(
            symbol=symbol,
            timeframe=timeframe,
            bars=bars_in_window,
            window_start=window_start,
            window_end=window_end,
            now=now,
            config=self.config,
            duplicate_count=self._ingestor.duplicate_count,
            out_of_order_count=self._ingestor.out_of_order_dropped_count,
        )
        if self.metrics is not None:
            if report.gap_count > 0:
                self.metrics.record_gap_detected(report.gap_count)
            if report.latency_seconds is not None:
                self.metrics.record_latency(report.latency_seconds)
        return report

    def get_health(self, now: datetime, gap_count: int = 0) -> PipelineHealth:
        return compute_pipeline_health(
            now=now,
            ticks_processed=self.ticks_processed,
            bars_produced=self.bars_produced,
            gap_count=gap_count,
        )

    def capture_replay(self, symbol: str):
        replay_series = self._recorder_for(symbol).to_replay_series()
        if self.metrics is not None:
            self.metrics.record_replay_readiness(is_replay_ready(replay_series))
        return replay_series

    def evict_expired_cache(self, now: datetime) -> None:
        self._cache.evict_expired(now)
