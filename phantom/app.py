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
from .metrics import MetricsRegistry
from .risk import RiskIntelligenceEngine
from .scanner import Scanner
from .strategies import StrategyEngine
from .trade_router import TradeRouter


class PhantomApp:
    def __init__(self, config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None):
        self.config = config
        self.sink = LogSink(path=log_path)
        self.strategies = StrategyEngine(config)
        self.orb = self.strategies.orb_engine  # backward-compatible reference
        self.performance = StrategyPerformanceTracker()
        self.metrics = MetricsRegistry()
        self.risk = RiskIntelligenceEngine(config)
        self.scanner = Scanner(config, sink=self.sink, strategy_engine=self.strategies,
                               metrics=self.metrics)
        # Advisory position sizing: compliance final, risk engine may only reduce.
        self.router = TradeRouter(config, self.risk, self.compliance)

    @property
    def compliance(self):
        """Read-only reference to the live ComplianceEngine (telemetry only)."""
        return self.scanner.scorer.guards.compliance

    def scan(self, snapshots):
        return self.scanner.scan(snapshots)

    def scan_symbol(self, snap):
        return self.scanner.scan_symbol(snap)

    def record_trade(self, strategy: str, pnl: float) -> None:
        """Feed a closed-trade result from the execution layer into analytics."""
        self.performance.record(strategy, pnl)
        self.risk.record_trade(pnl)  # additive: rolling stats for risk intelligence

    def update_account(self, **kw) -> None:
        """Feed live account telemetry (equity/balance/positions/news/regime/DD)
        into the Risk Intelligence Engine. Advisory only."""
        self.risk.update_account(**kw)

    def size_trade(self, symbol: str, equity: float, stop_distance: float,
                   current_dd_pct=None):
        """Advisory position size for a trade intent. Does not execute."""
        return self.router.size(symbol, equity, stop_distance, current_dd_pct)


def create_app(config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None) -> PhantomApp:
    return PhantomApp(config=config, log_path=log_path)
