"""`EABridgeEngine` — the EA bridge's top-level orchestrator (`ADR-023`).

Wires `DataPipeline` (existing, unmodified), `CommandQueue`, and
`EABrokerAdapter` together. Every handler here does exactly one of:
forward an EA-reported value to an already-existing pipeline entry point
(`DataPipeline.process_raw_tick()`/`load_historical_bars()`), store a
read-model snapshot (account state, positions, errors), or delegate to
`CommandQueue`/`EABrokerAdapter`. Nothing here computes a score, size,
SL/TP, or verdict (`ADR-023` Hard Rule 1).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from ..data_pipeline import DataPipeline
from ..data_pipeline.models import DataQuality, NormalizedBar
from ..data_pipeline.trace import make_trace_id
from .broker_adapter import EABrokerAdapter
from .command_queue import CommandQueue
from .config import EABridgeConfig
from .logging_sink import (
    log_account_state,
    log_emergency_stop,
    log_error_report,
    log_execution_report,
    log_heartbeat,
    log_position_report,
    log_tick,
)
from .metrics import EABridgeMetrics
from .models import (
    SCHEMA_VERSION,
    BarMessage,
    EAAccountState,
    EmergencyStopState,
    ErrorReport,
    ExecutionCommand,
    ExecutionReport,
    HeartbeatMessage,
    PositionReport,
    TickMessage,
)


class EABridgeEngine:
    def __init__(
        self,
        config: EABridgeConfig,
        data_pipeline: DataPipeline,
        command_queue: CommandQueue,
        broker_adapter: EABrokerAdapter,
        metrics: Optional[EABridgeMetrics] = None,
    ) -> None:
        self.config = config
        self._data_pipeline = data_pipeline
        self._queue = command_queue
        self._broker_adapter = broker_adapter
        self.metrics = metrics
        self._latest_account_state: Optional[EAAccountState] = None
        self._latest_positions: Dict[str, PositionReport] = {}
        self._errors: List[ErrorReport] = []
        self._emergency_stop = EmergencyStopState(active=False, reason=None, activated_at=None)

    # -- Inbound telemetry (ADR-023 §2.1) ----------------------------------

    def handle_heartbeat(self, message: HeartbeatMessage) -> None:
        self._broker_adapter.record_heartbeat(message.received_at)
        log_heartbeat(message)
        if self.metrics is not None:
            self.metrics.record_heartbeat()

    def handle_account_state(self, state: EAAccountState) -> None:
        self._latest_account_state = state
        self._broker_adapter.record_account_equity(state.equity)
        log_account_state(state)
        if self.metrics is not None:
            self.metrics.record_account_update()

    def handle_tick(self, tick: TickMessage) -> List[NormalizedBar]:
        """Forwarded verbatim to `DataPipeline.process_raw_tick()` — the
        same public ingestion entry point `market_data_adapter.MarketDataAdapter`
        already uses; no second normalization implementation here
        (`ADR-023` Hard Rule 3)."""
        bars = self._data_pipeline.process_raw_tick(
            raw_symbol=tick.symbol,
            raw_timestamp=tick.terminal_time,
            bid=tick.bid,
            ask=tick.ask,
            last=tick.last,
            volume=tick.volume,
            source="ea_bridge",
            market_status="OPEN",
        )
        log_tick(tick)
        if self.metrics is not None:
            self.metrics.record_tick()
        return bars

    def handle_bars(self, bars: Sequence[BarMessage]) -> None:
        """Forwarded verbatim to `DataPipeline.load_historical_bars()` —
        grouped by (symbol, timeframe) since that method takes one series
        at a time; no re-normalization of OHLC values here."""
        grouped: Dict[Tuple[str, str], List[NormalizedBar]] = defaultdict(list)
        for bar in bars:
            trace_id = make_trace_id("ea_bar", bar.symbol, bar.timeframe, bar.bar_time.isoformat())
            grouped[(bar.symbol, bar.timeframe)].append(
                NormalizedBar(
                    schema_version=SCHEMA_VERSION,
                    trace_id=trace_id,
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    timestamp=bar.bar_time,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    quality=DataQuality.NOMINAL,
                    is_repaired=False,
                    source="ea_bridge",
                )
            )
        for (symbol, timeframe), normalized_bars in grouped.items():
            self._data_pipeline.load_historical_bars(symbol, timeframe, normalized_bars)
        if self.metrics is not None:
            self.metrics.record_bars(len(bars))

    def handle_positions(self, positions: Sequence[PositionReport]) -> None:
        self._latest_positions = {p.position_id: p for p in positions}
        self._broker_adapter.record_open_position_ids(tuple(self._latest_positions.keys()))
        for position in positions:
            log_position_report(position)
        if self.metrics is not None:
            self.metrics.record_position_update()

    # -- Command relay (ADR-023 §2, Hard Rules 4, 5, 7) --------------------

    def poll_commands(self, now: datetime) -> Tuple[ExecutionCommand, ...]:
        return self._queue.poll(now)

    def handle_execution_report(self, report: ExecutionReport) -> bool:
        recorded = self._queue.record_result(report.execution_id, report)
        log_execution_report(report, recorded)
        if self.metrics is not None:
            if recorded:
                self.metrics.record_execution_report()
            else:
                self.metrics.record_duplicate_execution_report()
        return recorded

    def handle_error(self, error: ErrorReport) -> None:
        self._errors.append(error)
        log_error_report(error)
        if self.metrics is not None:
            self.metrics.record_error_report()

    # -- Emergency stop (ADR-023 Hard Rule 5) ------------------------------

    def activate_emergency_stop(self, reason: str, at: datetime) -> EmergencyStopState:
        self._queue.set_emergency_stop(True)
        self._emergency_stop = EmergencyStopState(active=True, reason=reason, activated_at=at)
        log_emergency_stop(self._emergency_stop)
        if self.metrics is not None:
            self.metrics.record_emergency_stop()
        return self._emergency_stop

    def deactivate_emergency_stop(self) -> EmergencyStopState:
        self._queue.set_emergency_stop(False)
        self._emergency_stop = EmergencyStopState(active=False, reason=None, activated_at=None)
        return self._emergency_stop

    # -- Read models --------------------------------------------------------

    @property
    def emergency_stop_state(self) -> EmergencyStopState:
        return self._emergency_stop

    @property
    def latest_account_state(self) -> Optional[EAAccountState]:
        return self._latest_account_state

    @property
    def latest_positions(self) -> Tuple[PositionReport, ...]:
        return tuple(self._latest_positions.values())

    @property
    def errors(self) -> Tuple[ErrorReport, ...]:
        return tuple(self._errors)


__all__ = ["EABridgeEngine"]
