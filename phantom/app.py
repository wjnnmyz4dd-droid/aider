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
from datetime import datetime, timezone

from .account import AccountFeed, AccountSnapshot, parse_timestamp
from .metrics import MetricsRegistry
from .risk import RiskIntelligenceEngine
from .scanner import Scanner
from .strategies import StrategyEngine
from .trade_router import TradeRouter
from .types import MarketSnapshot


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
        self.account = AccountFeed(ttl_seconds=config.account_feed_ttl_seconds)
        # Advisory position sizing: compliance final, risk engine may only reduce.
        self.router = TradeRouter(config, self.risk, self.compliance, account_feed=self.account)

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

    # ---- live account feed -----------------------------------------------
    def apply_account_snapshot(self, payload: dict) -> dict:
        """Ingest a live MT5/broker account snapshot: store it, drive compliance
        off live equity, and update risk telemetry. Returns the account status."""
        ts = parse_timestamp(payload.get("timestamp"))
        snap = AccountSnapshot(
            balance=float(payload["balance"]),
            equity=float(payload["equity"]),
            margin=float(payload.get("margin", 0.0)),
            free_margin=float(payload.get("free_margin", 0.0)),
            positions_open=int(payload.get("positions_open", 0)),
            timestamp=ts,
        )
        self.account.update(snap)
        # ComplianceEngine drives off LIVE equity (final authority; can only tighten).
        self.compliance.check(MarketSnapshot(symbol="ACCOUNT", now=ts, candles={}, equity=snap.equity))
        cs = self.compliance.state(ts)
        # Risk telemetry.
        self.update_account(equity=snap.equity, balance=snap.balance,
                            positions_open=snap.positions_open,
                            daily_dd_pct=cs["daily_dd_pct"], total_dd_pct=cs["total_dd_pct"])
        return self.account_status(datetime.now(timezone.utc))

    def account_status(self, now=None) -> dict:
        now = now or datetime.now(timezone.utc)
        cs = self.compliance.state(now)
        rt = self.risk.telemetry(cs["total_dd_pct"])
        last = self.account.last()
        stale = self.account.is_stale(now)
        allowed = (rt["trading_allowed"] and not cs["killswitch_active"]
                   and not cs["daily_lockout"] and not stale)
        return {
            "balance": last.balance if last else None,
            "equity": cs["equity"],
            "daily_drawdown_pct": cs["daily_dd_pct"],
            "total_drawdown_pct": cs["total_dd_pct"],
            "trading_allowed": allowed,
            "killswitch_active": cs["killswitch_active"],
            "daily_lockout": cs["daily_lockout"],
            "positions_open": last.positions_open if last else 0,
            "last_update_age_seconds": self.account.age_seconds(now),
            "account_feed_stale": stale,
        }


def create_app(config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None) -> PhantomApp:
    return PhantomApp(config=config, log_path=log_path)
