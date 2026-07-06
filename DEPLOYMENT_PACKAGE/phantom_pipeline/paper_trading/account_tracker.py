"""Account equity / drawdown tracking for the Paper Trading Runner
(Phase 4).

**Fills a gap this architecture always assumed existed externally.**
`risk_engine.models.AccountState.daily_drawdown_pct`/`total_drawdown_pct`
and `compliance_engine.models.AccountState`'s equivalent fields are
documented, in both engines' own docstrings, as caller-supplied inputs —
"any field left `None` means that specific input cannot be reliably
evaluated" — neither engine computes these percentages itself; something
upstream always had to. No such upstream computation exists anywhere in
this repository until now. `AccountTracker` is exactly that upstream
computation: it turns one raw equity reading (from `MT5Adapter.
query_account_equity()`, or any equivalent source) into the two
percentages both engines already expect, using `SessionManager`'s
trading-day boundary to know when to re-baseline the day-start reading.

**Never a second risk/compliance authority.** `AccountTracker` computes a
percentage from arithmetic on already-observed equity numbers — it never
approves, blocks, sizes, or evaluates anything; every one of those
remains exclusively Risk Engine's/Compliance Engine's own job. This
class's only output, `AccountSnapshot`, is a plain data record a caller
then passes into those engines' own `AccountState` construction (never
this module's own).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .session_manager import SessionManager

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AccountSnapshot:
    """One observed equity reading and its derived drawdown percentages.
    `total_drawdown_pct_from_peak` is the trailing (high-water-mark)
    reading some prop firms use instead of `total_drawdown_pct`'s
    static-initial-balance reading (`PropFirmProfile.total_drawdown_basis`
    picks which one a given profile is evaluated against) — both are
    reported so no information is discarded."""

    schema_version: int
    equity: float
    day_start_equity: float
    initial_equity: float
    peak_equity: float
    daily_drawdown_pct: float
    total_drawdown_pct: float
    total_drawdown_pct_from_peak: float
    timestamp: datetime


class AccountTracker:
    def __init__(self, initial_equity: float, session_manager: Optional[SessionManager] = None) -> None:
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self._initial_equity = initial_equity
        self._day_start_equity = initial_equity
        self._peak_equity = initial_equity
        self._session_manager = session_manager or SessionManager()
        self._current_trading_day_start: Optional[datetime] = None

    def observe(self, equity: float, now: datetime) -> AccountSnapshot:
        if self._current_trading_day_start is None:
            self._current_trading_day_start = self._session_manager.trading_day_start(now)
            self._day_start_equity = equity
        elif self._session_manager.is_new_trading_day(self._current_trading_day_start, now):
            self._current_trading_day_start = self._session_manager.trading_day_start(now)
            self._day_start_equity = equity

        self._peak_equity = max(self._peak_equity, equity)

        daily_drawdown_pct = _drawdown_pct(self._day_start_equity, equity)
        total_drawdown_pct = _drawdown_pct(self._initial_equity, equity)
        total_drawdown_pct_from_peak = _drawdown_pct(self._peak_equity, equity)

        return AccountSnapshot(
            schema_version=SCHEMA_VERSION,
            equity=equity,
            day_start_equity=self._day_start_equity,
            initial_equity=self._initial_equity,
            peak_equity=self._peak_equity,
            daily_drawdown_pct=daily_drawdown_pct,
            total_drawdown_pct=total_drawdown_pct,
            total_drawdown_pct_from_peak=total_drawdown_pct_from_peak,
            timestamp=now,
        )


def _drawdown_pct(baseline: float, current: float) -> float:
    if baseline <= 0:
        return 0.0
    return max(0.0, (baseline - current) / baseline * 100.0)


__all__ = ["AccountSnapshot", "AccountTracker"]
