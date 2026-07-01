"""Statistical Risk Intelligence Engine (additive, advisory, fail-safe).

Adapts per-trade risk % from rolling live performance and drawdown, within a
hard [0.25%, 1.00%] band. It is ADVISORY: it never executes, never loosens an
existing protection, and cannot raise risk on error. FTMO daily/total limits and
the ComplianceEngine remain the authoritative gate — this engine only tightens.

Fail-safe (Phase 5): any internal error -> DEFENSIVE at minimum risk; risk is
never increased automatically; existing protections continue unaffected.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, List, Optional

from .config import Config, DEFAULT_CONFIG


class RiskMode(str, Enum):
    DEFENSIVE = "DEFENSIVE"
    NORMAL = "NORMAL"
    AGGRESSIVE = "AGGRESSIVE"


_ORDER = [RiskMode.DEFENSIVE, RiskMode.NORMAL, RiskMode.AGGRESSIVE]


@dataclass
class RollingStats:
    trades: int
    win_rate: float
    expectancy: float
    profit_factor: Optional[float]  # None == infinite (no losses)
    consecutive_wins: int
    consecutive_losses: int


@dataclass
class RiskState:
    mode: RiskMode
    risk_pct: float
    trading_allowed: bool
    pause_until_next_session: bool
    lockout: bool
    dd_level: int
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "risk_pct": round(self.risk_pct, 4),
            "trading_allowed": self.trading_allowed,
            "pause_until_next_session": self.pause_until_next_session,
            "lockout": self.lockout,
            "dd_level": self.dd_level,
            "reasons": self.reasons,
        }


class RiskIntelligenceEngine:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self._lock = threading.Lock()
        self._pnl: Deque[float] = deque(maxlen=config.risk.window)
        self._cons_wins = 0
        self._cons_losses = 0
        self._account = {
            "equity": None, "balance": None, "positions_open": 0,
            "news_block": False, "regime": "UNKNOWN",
            "daily_dd_pct": None, "total_dd_pct": None,
        }
        self._last_mode: Optional[RiskMode] = None
        self._adj_day: Optional[str] = None
        self._adjustments_today = 0

    # ---- inputs -----------------------------------------------------------
    def record_trade(self, pnl: float) -> None:
        with self._lock:
            self._pnl.append(float(pnl))
            if pnl > 0:
                self._cons_wins += 1
                self._cons_losses = 0
            elif pnl < 0:
                self._cons_losses += 1
                self._cons_wins = 0

    def update_account(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                if k in self._account:
                    self._account[k] = v

    # ---- stats ------------------------------------------------------------
    def rolling_stats(self) -> RollingStats:
        with self._lock:
            pnls = list(self._pnl)
            cw, cl = self._cons_wins, self._cons_losses
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = -sum(p for p in pnls if p < 0)
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit > 0 else 0.0)
        return RollingStats(
            trades=n,
            win_rate=(wins / n) if n else 0.0,
            expectancy=(sum(pnls) / n) if n else 0.0,
            profit_factor=pf,
            consecutive_wins=cw,
            consecutive_losses=cl,
        )

    # ---- tiering ----------------------------------------------------------
    def _base_tier(self, stats: RollingStats, dd_pct: float) -> RiskMode:
        r = self.config.risk
        pf = float("inf") if stats.profit_factor is None else stats.profit_factor
        if dd_pct > r.def_dd_pct or pf < r.def_profit_factor or stats.win_rate < r.def_win_rate:
            return RiskMode.DEFENSIVE
        if (pf > r.agg_profit_factor and stats.win_rate > r.agg_win_rate
                and stats.trades >= r.agg_min_trades):
            return RiskMode.AGGRESSIVE
        return RiskMode.NORMAL

    def _risk_for(self, mode: RiskMode) -> float:
        r = self.config.risk
        return {RiskMode.DEFENSIVE: r.risk_defensive,
                RiskMode.NORMAL: r.risk_normal,
                RiskMode.AGGRESSIVE: r.risk_aggressive}[mode]

    # ---- evaluation -------------------------------------------------------
    def evaluate(self, current_dd_pct: Optional[float] = None) -> RiskState:
        r = self.config.risk
        try:
            stats = self.rolling_stats()
            dd = current_dd_pct
            if dd is None:
                dd = self._account.get("total_dd_pct") or 0.0
            reasons: List[str] = []

            mode = self._base_tier(stats, dd)
            risk = self._risk_for(mode)
            pause = lockout = False
            dd_level = 0

            # Phase 2 — progressive drawdown (monotonic tightening).
            if dd > r.dd_level4:
                dd_level, lockout = 4, True
                mode, risk = RiskMode.DEFENSIVE, r.risk_min
                reasons.append(f"DD>{r.dd_level4}%: compliance lockout")
            elif dd > r.dd_level3:
                dd_level, pause = 3, True
                mode, risk = RiskMode.DEFENSIVE, r.risk_min
                reasons.append(f"DD>{r.dd_level3}%: pause until next session")
            elif dd > r.dd_level2:
                dd_level = 2
                mode, risk = RiskMode.DEFENSIVE, r.risk_min
                reasons.append(f"DD>{r.dd_level2}%: risk to minimum")
            elif dd > r.dd_level1:
                dd_level = 1
                idx = max(0, _ORDER.index(mode) - 1)
                mode = _ORDER[idx]
                risk = self._risk_for(mode)
                reasons.append(f"DD>{r.dd_level1}%: reduce tier by one")

            risk = max(r.risk_min, min(risk, r.risk_max))  # hard band
            trading_allowed = not (pause or lockout)
            self._track_adjustment(mode)
            if not reasons:
                reasons.append(f"{mode.value} (wr={stats.win_rate:.0%}, pf={_pf(stats)}, n={stats.trades})")
            return RiskState(mode, risk, trading_allowed, pause, lockout, dd_level, reasons)
        except Exception as exc:  # Phase 5 fail-safe — never raises, never raises risk
            return RiskState(RiskMode.DEFENSIVE, r.risk_min, True, False, False, 0,
                             [f"fail-safe: risk-engine error ({type(exc).__name__})"])

    def _track_adjustment(self, mode: RiskMode) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            if self._adj_day != day:
                self._adj_day, self._adjustments_today = day, 0
            if self._last_mode is not None and mode != self._last_mode:
                self._adjustments_today += 1
            self._last_mode = mode

    # ---- telemetry / analytics -------------------------------------------
    def telemetry(self, current_dd_pct: Optional[float] = None) -> dict:
        st = self.evaluate(current_dd_pct)
        with self._lock:
            acc = dict(self._account)
        return {
            "risk_mode": st.mode.value,
            "current_risk_pct": st.risk_pct,
            "trading_allowed": st.trading_allowed,
            "pause_until_next_session": st.pause_until_next_session,
            "lockout": st.lockout,
            "dd_level": st.dd_level,
            "account": acc,
        }

    def analytics(self, compliance_status: str = "UNKNOWN",
                  current_dd_pct: Optional[float] = None,
                  peak_dd_pct: Optional[float] = None) -> dict:
        st = self.evaluate(current_dd_pct)
        stats = self.rolling_stats()
        with self._lock:
            adjustments = self._adjustments_today
        return {
            "current_risk_mode": st.mode.value,
            "current_risk_pct": st.risk_pct,
            "expected_monthly_risk_pct": round(st.risk_pct * self.config.risk.expected_trades_per_month, 2),
            "rolling_win_rate": round(stats.win_rate, 4),
            "rolling_expectancy": round(stats.expectancy, 4),
            "rolling_profit_factor": stats.profit_factor,
            "risk_adjustments_today": adjustments,
            "compliance_status": compliance_status,
            "current_drawdown_pct": current_dd_pct if current_dd_pct is not None else 0.0,
            "peak_drawdown_pct": peak_dd_pct if peak_dd_pct is not None else 0.0,
        }


def _pf(stats: RollingStats) -> str:
    return "inf" if stats.profit_factor is None else f"{stats.profit_factor:.2f}"
