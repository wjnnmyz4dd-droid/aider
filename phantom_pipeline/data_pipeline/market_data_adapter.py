"""A real market-data adapter backed by the official `MetaTrader5` Python
package (ADR-013 §4's "MT5 Broker Feed" input, ADR-015's Adapter Forbidden
Responsibilities). `data_pipeline/models.py`'s own `DataQualityReport.
latency_seconds` docstring already anticipated this: "Phase 1 has no live
broker feed adapter yet... until a real feed supplies a receipt time."

**Translation only.** `MarketDataAdapter` never constructs a `NormalizedTick`/
`NormalizedBar`/`HistoricalSeries` itself in the sense of deciding its
content — every field is a direct mapping from the vendor's own tick/rate
shape. All actual normalization (symbol/timestamp/price/volume, duplicate
and out-of-order detection, gap flagging) still happens exactly once,
inside `DataPipeline`/`TickIngestor`/`BarBuilder` — this adapter is purely
the thing that calls `DataPipeline.process_raw_tick`/`load_historical_bars`/
`warm_start` with real vendor data instead of a test's synthetic values.

**Live vs. historical, and replay compatibility.** `poll_ticks` feeds
`DataPipeline.process_raw_tick` — the same live-ingestion path
`replay.replay_through` re-drives during a replay run, so a live tick and a
replayed tick are normalized identically and both get captured into
`ReplayRecorder` (ADR-013 §10). `load_historical`/`warm_start` feed
`DataPipeline.load_historical_bars`/`warm_start` — the bulk-load path that
is deliberately *not* captured into replay (`historical.py`'s own
docstring: "loading bulk history is not a live event"), so warm-starting
the cache from real vendor history never corrupts replay determinism for
genuinely live-produced data.

**Why the MT5 client is injectable**: identical rationale to
`mt5_bridge.mt5_adapter.MT5Adapter` — the real `MetaTrader5` package only
runs against a live MT5 terminal and cannot be installed in every
environment; lazy-imported inside `connect()`, never at module load time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import DEFAULT_CONFIG, PipelineConfig
from .models import DataQuality, HistoricalSeries, NormalizedBar, SCHEMA_VERSION
from .pipeline import DataPipeline
from .trace import make_trace_id

_TIMEFRAME_TO_MT5_CONSTANT = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def _import_metatrader5() -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "MarketDataAdapter requires the official 'MetaTrader5' package "
            "and a running MT5 terminal; install it or pass mt5_module= for "
            "testing."
        ) from exc
    return mt5


def _field(rate: Any, name: str) -> Any:
    """Reads one field off a vendor rate record. The real MT5 package
    returns a numpy structured array (subscript access); a plain object
    or mapping (attribute/dict access) is also accepted so this stays
    testable without numpy."""
    try:
        return rate[name]
    except (TypeError, IndexError, KeyError):
        pass
    if isinstance(rate, dict):
        return rate[name]
    return getattr(rate, name)


class MarketDataAdapter:
    """Real MT5-backed tick/historical-data source, feeding an
    already-constructed `DataPipeline` via its existing public methods
    only."""

    def __init__(self, mt5_module: Optional[Any] = None, config: PipelineConfig = DEFAULT_CONFIG) -> None:
        self._mt5 = mt5_module
        self._config = config

    def _client(self) -> Any:
        if self._mt5 is None:
            self._mt5 = _import_metatrader5()
        return self._mt5

    def connect(self) -> bool:
        return bool(self._client().initialize())

    def disconnect(self) -> None:
        self._client().shutdown()

    # -- Live ingestion (ADR-013 §4, §6) ---------------------------------

    def poll_ticks(
        self,
        pipeline: DataPipeline,
        symbol: str,
        mt5_symbol: Optional[str] = None,
        market_status: str = "OPEN",
    ) -> List[NormalizedBar]:
        """Fetches the latest tick for `symbol` and feeds it through
        `pipeline.process_raw_tick` — the same live path replay re-drives,
        so this call is automatically replay-compatible. Returns any bar(s)
        finalized by it, or an empty list if no new tick is available."""
        tick = self._client().symbol_info_tick(mt5_symbol or symbol)
        if tick is None:
            return []
        raw_last = _field(tick, "last") if _has_field(tick, "last") else None
        raw_volume = _field(tick, "volume") if _has_field(tick, "volume") else None
        timestamp = datetime.fromtimestamp(_field(tick, "time"), tz=timezone.utc)
        return pipeline.process_raw_tick(
            raw_symbol=symbol,
            raw_timestamp=timestamp,
            bid=_field(tick, "bid"),
            ask=_field(tick, "ask"),
            last=raw_last or None,
            volume=raw_volume,
            source="mt5_live",
            market_status=market_status,
        )

    # -- Historical loading / warm cache (ADR-013 §4, §11) ---------------

    def load_historical(
        self,
        pipeline: DataPipeline,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        mt5_symbol: Optional[str] = None,
    ) -> HistoricalSeries:
        """Bulk-loads `symbol`/`timeframe` history for `[start, end]` from
        MT5 directly into `pipeline`'s historical cache
        (`DataPipeline.load_historical_bars`) — never through tick
        ingestion, never captured into replay (`historical.py`'s own
        contract)."""
        mt5 = self._client()
        constant_name = _TIMEFRAME_TO_MT5_CONSTANT.get(timeframe)
        if constant_name is None:
            raise ValueError(f"unsupported timeframe for MT5 historical load: {timeframe!r}")
        rates = mt5.copy_rates_range(mt5_symbol or symbol, getattr(mt5, constant_name), start, end)
        bars = [self._translate_rate(rate, symbol, timeframe) for rate in (rates if rates is not None else ())]
        pipeline.load_historical_bars(symbol, timeframe, bars)
        return pipeline.get_historical_series(symbol, timeframe)

    def warm_start(
        self,
        pipeline: DataPipeline,
        symbol_timeframes: Sequence[Tuple[str, str]],
        start: datetime,
        end: datetime,
        mt5_symbols: Optional[Dict[str, str]] = None,
    ) -> None:
        """Bootstraps the historical cache for many symbol/timeframe pairs
        at once (ADR-013 §11's warm-cache bootstrap), reusing
        `load_historical` per pair and `pipeline.warm_start` to install
        them all through the one sanctioned bulk entry point."""
        mt5_symbols = mt5_symbols or {}
        series_list = [
            self.load_historical(pipeline, symbol, timeframe, start, end, mt5_symbols.get(symbol))
            for symbol, timeframe in symbol_timeframes
        ]
        pipeline.warm_start(series_list)

    def _translate_rate(self, rate: Any, symbol: str, timeframe: str) -> NormalizedBar:
        timestamp = datetime.fromtimestamp(_field(rate, "time"), tz=timezone.utc)
        trace_id = make_trace_id("mt5_history", symbol, timeframe, timestamp.isoformat())
        return NormalizedBar(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            open=float(_field(rate, "open")),
            high=float(_field(rate, "high")),
            low=float(_field(rate, "low")),
            close=float(_field(rate, "close")),
            volume=float(_field(rate, "tick_volume")),
            quality=DataQuality.NOMINAL,
            is_repaired=False,
            source="mt5_history",
        )


def _has_field(rate: Any, name: str) -> bool:
    try:
        _field(rate, name)
        return True
    except (AttributeError, KeyError, IndexError, TypeError):
        return False


__all__ = ["MarketDataAdapter"]
