"""Application wiring: a single object that owns the shared pipeline state.

Holding the strategy engine, scanner, log sink and performance tracker together
means the API can report exactly what the scanner has seen, with no duplicate
state.
"""

from __future__ import annotations

from typing import Optional

from .analytics import StrategyPerformanceTracker
from .config import Config, DEFAULT_CONFIG
from .logging_sink import LogSink
from .scanner import Scanner
from .strategies import StrategyEngine


class PhantomApp:
    def __init__(self, config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None):
        self.config = config
        self.sink = LogSink(path=log_path)
        self.strategies = StrategyEngine(config)
        self.orb = self.strategies.orb_engine  # backward-compatible reference
        self.performance = StrategyPerformanceTracker()
        self.scanner = Scanner(config, sink=self.sink, strategy_engine=self.strategies)

    def scan(self, snapshots):
        return self.scanner.scan(snapshots)

    def scan_symbol(self, snap):
        return self.scanner.scan_symbol(snap)

    def record_trade(self, strategy: str, pnl: float) -> None:
        """Feed a closed-trade result from the execution layer into analytics."""
        self.performance.record(strategy, pnl)


def create_app(config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None) -> PhantomApp:
    return PhantomApp(config=config, log_path=log_path)
