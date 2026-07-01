"""Per-strategy performance analytics.

Stats are computed from REAL recorded trade results only — nothing is
fabricated. Until an execution layer reports closed trades via :meth:`record`,
every strategy reports zeros. This module never opens or simulates trades.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

STRATEGIES = ("ORB", "Liquidity Reversal", "Session Breakout")


def _stats(pnls: List[float]) -> dict:
    trades = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)  # positive magnitude
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    return {
        "trades": trades,
        "win_rate": round(wins / trades, 4) if trades else 0.0,
        "profit_factor": (round(profit_factor, 4) if profit_factor != float("inf") else None),
        "pl": round(sum(pnls), 2),
    }


class StrategyPerformanceTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._pnl: Dict[str, List[float]] = {s: [] for s in STRATEGIES}

    def record(self, strategy: str, pnl: float) -> None:
        if strategy not in self._pnl:
            raise KeyError(f"unknown strategy: {strategy}")
        with self._lock:
            self._pnl[strategy].append(float(pnl))

    def stats(self, strategy: str) -> dict:
        with self._lock:
            return _stats(list(self._pnl[strategy]))

    def _rank_key(self, s: dict):
        # Rank by profit factor (inf treated as very large), tie-break on P/L.
        pf = s["profit_factor"]
        pf_val = float("inf") if pf is None and s["pl"] > 0 else (pf or 0.0)
        return (pf_val, s["pl"])

    def panel(self) -> dict:
        with self._lock:
            per = {s: _stats(list(self._pnl[s])) for s in STRATEGIES}
        traded = {s: v for s, v in per.items() if v["trades"] > 0}
        best = max(traded, key=lambda s: self._rank_key(traded[s])) if traded else None
        worst = min(traded, key=lambda s: self._rank_key(traded[s])) if traded else None
        return {"strategies": per, "best": best, "worst": worst}
