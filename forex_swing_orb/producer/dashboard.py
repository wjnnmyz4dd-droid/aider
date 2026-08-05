"""Read-only runner status (Phase 7A). Informational only; never influences trading.

It reads persisted state, the runner audit, and (read-only) the bridge/compliance
evidence. It performs no evaluation, writes nothing, and places/modifies nothing.
"""

from __future__ import annotations

from ..bridge import serialize
from . import ingest
from .contract import RunnerMode


class RunnerDashboard:
    def __init__(self, runner):
        self._r = runner

    def status(self, now):
        r = self._r
        acct = None
        try:
            acct = r.account.snapshot(now)
        except Exception:
            acct = None
        demo_verified = bool(isinstance(acct, dict) and acct.get("is_demo") is True
                             and acct.get("account_type") == "DEMO")
        terminal = acct.get("terminal_connected") if isinstance(acct, dict) else None

        news = None
        try:
            news = r.news.bundle(now)
        except Exception:
            news = None
        news_as_of = news.get("as_of") if isinstance(news, dict) else None

        statuses = ingest.ingest(r.paths, list(r.state.written_signals))
        unresolved = [sid for sid, st in statuses.items() if st["reconcile_required"]]
        pending = [sid for sid, st in statuses.items() if st["in_flight"]]

        cycles = r.audit.read_all()
        last_cycle = cycles[-1] if cycles else None

        return {
            "service_state": "READY" if demo_verified else "REFUSED",
            "mode": r.config.mode,
            "demo_verified": demo_verified,
            "ftmo_profile_verified": r.config.ftmo_profile_verified,
            "mt5_connected": terminal,
            "last_cycle": last_cycle,
            "last_processed_bar": dict(r.state.last_processed),
            "news_as_of": news_as_of,
            "pending_instructions": pending,
            "unresolved_reconciliations": unresolved,
            "written_signal_count": len(r.state.written_signals),
            "last_error": r.last_error,
            "session": getattr(r, "_last_session_snapshot", None),   # Phase 9A
        }
