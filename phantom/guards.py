"""Blocking guards and the session filter.

Guards answer a yes/no question. When a guard fails it forces the scanner's
decision to BLOCK regardless of the additive score. The session filter is a
soft component (awards points) and lives here because it shares the clock
helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from .config import Config, DEFAULT_CONFIG
from .types import Direction, MarketSnapshot, NewsState


@dataclass
class GuardResult:
    passed: bool
    detail: str = ""


def _symbol_currencies(symbol: str) -> List[str]:
    """Split a 6-letter FX symbol into its two currencies; metals -> base+USD."""
    s = symbol.upper()
    if len(s) == 6:
        return [s[:3], s[3:]]
    if s.startswith("XAU") or s.startswith("XAG"):
        return [s[:3], "USD"]
    return [s]


class Guards:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config

    # --- News --------------------------------------------------------------
    def news_state(self, snap: MarketSnapshot) -> NewsState:
        ccys = set(_symbol_currencies(snap.symbol))
        for w in snap.news_windows:
            if w.currency.upper() in ccys and w.start <= snap.now <= w.end:
                return NewsState.DANGER
        return NewsState.SAFE

    def news(self, snap: MarketSnapshot) -> GuardResult:
        state = self.news_state(snap)
        return GuardResult(state == NewsState.SAFE, f"news={state.value}")

    # --- Spread ------------------------------------------------------------
    def spread(self, snap: MarketSnapshot) -> GuardResult:
        ok = snap.spread <= self.config.guards.max_spread
        return GuardResult(ok, f"spread={snap.spread:.5f}<= {self.config.guards.max_spread:.5f}")

    # --- Correlation: at most N open trades per correlation bucket. --------
    def correlation(self, snap: MarketSnapshot, direction: Direction) -> GuardResult:
        groups = self.config.guards.correlation_groups
        bucket = groups.get(snap.symbol.upper())
        if bucket is None:
            return GuardResult(True, "no correlation bucket")
        same = 0
        for sym, d in snap.open_positions.items():
            if sym.upper() == snap.symbol.upper():
                continue
            if groups.get(sym.upper()) == bucket:
                same += 1
        ok = same < self.config.guards.max_open_per_bucket
        return GuardResult(ok, f"bucket={bucket} open={same}")

    # --- Exposure: no conflicting open position on the same symbol. --------
    def exposure(self, snap: MarketSnapshot, direction: Direction) -> GuardResult:
        existing = snap.open_positions.get(snap.symbol.upper())
        if existing is None:
            return GuardResult(True, "flat")
        if existing == direction:
            return GuardResult(True, f"already {direction.value} (stack ok)")
        return GuardResult(False, f"conflict: open {existing.value} vs {direction.value}")

    # --- Prop compliance: daily drawdown limit. ----------------------------
    def prop_compliance(self, snap: MarketSnapshot) -> GuardResult:
        limit = self.config.guards.max_account_drawdown_pct
        ok = snap.account_drawdown_pct < limit
        return GuardResult(ok, f"dd={snap.account_drawdown_pct:.2f}% < {limit:.2f}%")

    # --- RR validation: caller supplies the computed RR. -------------------
    def rr_validation(self, rr: Optional[float]) -> GuardResult:
        if rr is None:
            return GuardResult(False, "rr=unknown")
        ok = rr >= self.config.guards.min_rr
        return GuardResult(ok, f"rr={rr:.2f} >= {self.config.guards.min_rr:.2f}")

    # --- Session filter (soft component): is now inside an active FX session?
    def in_active_session(self, now: datetime) -> bool:
        for tz, (start_h, end_h) in {
            self.config.orb.london_tz: (7, 16),
            self.config.orb.newyork_tz: (8, 17),
        }.items():
            local = now.astimezone(ZoneInfo(tz))
            if local.weekday() < 5 and start_h <= local.hour < end_h:
                return True
        return False
