"""Blocking guards and the session filter.

Guards answer a yes/no question. When a guard fails it forces the scanner's
decision to BLOCK regardless of the additive score. The session filter is a
soft component (awards points) and lives here because it shares the clock
helpers.
"""

from __future__ import annotations

import threading
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


class ComplianceEngine:
    """FIX 4 — stateful prop-firm drawdown tracking off LIVE equity.

    Tracks the all-time equity peak (for total DD), the daily start/peak equity
    (for daily DD), and latches a hard kill-switch (total-DD breach, permanent)
    and a daily lockout (daily-DD breach, resets next day). Falls back to the
    legacy scalar when no equity is supplied, so behaviour is unchanged for
    callers that don't feed equity.
    """

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self._lock = threading.Lock()
        self._peak_equity: Optional[float] = None
        self._day: Optional[str] = None
        self._daily_peak: Optional[float] = None
        self._killed = False          # permanent (total-DD breach)
        self._locked_day: Optional[str] = None  # daily lockout marker

    def check(self, snap: MarketSnapshot) -> GuardResult:
        g = self.config.guards
        if snap.equity is None:
            # Legacy fallback — unchanged behaviour.
            ok = snap.account_drawdown_pct < g.max_account_drawdown_pct
            return GuardResult(ok, f"dd={snap.account_drawdown_pct:.2f}% < {g.max_account_drawdown_pct:.2f}% (legacy)")

        day = snap.now.astimezone().date().isoformat()
        with self._lock:
            if self._peak_equity is None:
                self._peak_equity = snap.equity
            if self._day != day:
                self._day = day
                self._daily_peak = snap.equity
            self._peak_equity = max(self._peak_equity, snap.equity)
            self._daily_peak = max(self._daily_peak or snap.equity, snap.equity)

            total_dd = (self._peak_equity - snap.equity) / self._peak_equity * 100 if self._peak_equity else 0.0
            daily_dd = (self._daily_peak - snap.equity) / self._daily_peak * 100 if self._daily_peak else 0.0

            if self._killed:
                return GuardResult(False, "KILL_SWITCH: total-DD breach (locked)")
            if total_dd >= g.max_total_dd_pct:
                self._killed = True
                return GuardResult(False, f"KILL_SWITCH: total_dd={total_dd:.2f}% >= {g.max_total_dd_pct:.2f}%")
            if self._locked_day == day:
                return GuardResult(False, "DAILY_LOCKOUT: daily-DD breach (locked today)")
            if daily_dd >= g.max_daily_dd_pct:
                self._locked_day = day
                return GuardResult(False, f"DAILY_LOCKOUT: daily_dd={daily_dd:.2f}% >= {g.max_daily_dd_pct:.2f}%")
            return GuardResult(True, f"daily_dd={daily_dd:.2f}% total_dd={total_dd:.2f}% ok")


class Guards:
    def __init__(self, config: Config = DEFAULT_CONFIG,
                 compliance: Optional[ComplianceEngine] = None):
        self.config = config
        self.compliance = compliance or ComplianceEngine(config)

    def _symbol_currencies(self, symbol: str) -> List[str]:
        """Currencies whose news affects ``symbol``. FIX 6 — non-FX instruments
        resolve through the instrument exposure map; 6-letter FX splits into its
        two legs; metals fall back to base+USD."""
        s = symbol.upper()
        mapped = self.config.guards.instrument_exposure_map.get(s)
        if mapped:
            return [c.upper() for c in mapped]
        if len(s) == 6:
            return [s[:3], s[3:]]
        if s.startswith("XAU") or s.startswith("XAG"):
            return [s[:3], "USD"]
        return [s]

    # --- News --------------------------------------------------------------
    def news_state(self, snap: MarketSnapshot) -> NewsState:
        ccys = set(self._symbol_currencies(snap.symbol))
        for w in snap.news_windows:
            if w.currency.upper() in ccys and w.start <= snap.now <= w.end:
                return NewsState.DANGER
        return NewsState.SAFE

    def news(self, snap: MarketSnapshot) -> GuardResult:
        state = self.news_state(snap)
        return GuardResult(state == NewsState.SAFE, f"news={state.value}")

    # --- Spread (FIX 5 — symbol-aware, pip-normalized) --------------------
    def spread(self, snap: MarketSnapshot) -> GuardResult:
        g = self.config.guards
        prof = g.symbol_profiles.get(snap.symbol.upper())
        if prof is None:  # unknown symbol -> legacy absolute cap
            ok = snap.spread <= g.max_spread
            return GuardResult(ok, f"spread={snap.spread:.5f} <= {g.max_spread:.5f} (default)")
        points = snap.spread / prof.pip_size if prof.pip_size else float("inf")
        ok = points <= prof.max_spread_points
        return GuardResult(ok, f"spread={points:.1f}pt <= {prof.max_spread_points:.1f}pt")

    # --- Correlation (FIX 3 — fail-closed for unknown symbols) -------------
    def _bucket_for(self, symbol: str) -> Optional[str]:
        g = self.config.guards
        bucket = g.correlation_groups.get(symbol.upper())
        if bucket is None and g.derive_correlation_bucket:
            ccys = self._symbol_currencies(symbol)
            if len(ccys) == 2:
                bucket = f"CCY_{ccys[0]}"  # derived from the base leg
        return bucket

    def correlation(self, snap: MarketSnapshot, direction: Direction) -> GuardResult:
        g = self.config.guards
        sym = snap.symbol.upper()
        bucket = self._bucket_for(sym)
        if bucket is None:
            if g.correlation_fail_closed:
                return GuardResult(False, "UNKNOWN_CORRELATION_BUCKET")
            return GuardResult(True, "no correlation bucket")
        same = 0
        for other in snap.open_positions:
            if other.upper() == sym:
                continue
            if self._bucket_for(other) == bucket:
                same += 1
        ok = same < g.max_open_per_bucket
        return GuardResult(ok, f"bucket={bucket} open={same}")

    # --- Exposure (FIX 2 — block same-direction stacking) -----------------
    def exposure(self, snap: MarketSnapshot, direction: Direction) -> GuardResult:
        g = self.config.guards
        sym = snap.symbol.upper()
        existing = snap.open_positions.get(sym)
        if existing is not None and existing != direction:
            return GuardResult(False, f"conflict: open {existing.value} vs {direction.value}")
        count = snap.position_counts.get(sym)
        if count is None:
            count = 1 if existing is not None else 0
        if count > 0 and count >= g.max_positions_per_symbol and not g.allow_stacking:
            return GuardResult(False, f"max positions/symbol reached ({count} >= {g.max_positions_per_symbol})")
        expo = snap.symbol_exposure_pct.get(sym, 0.0)
        if expo >= g.max_symbol_exposure_pct:
            return GuardResult(False, f"symbol exposure {expo:.1f}% >= {g.max_symbol_exposure_pct:.1f}%")
        return GuardResult(True, "flat" if count == 0 else f"{count} open (ok)")

    # --- Prop compliance (FIX 4 — live-equity DD / kill-switch / lockout) --
    def prop_compliance(self, snap: MarketSnapshot) -> GuardResult:
        return self.compliance.check(snap)

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
