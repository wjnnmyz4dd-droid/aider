"""Runtime status snapshots written to files (Phase 8D, item 6).

Dashboards are surfaced by writing read-only status files (no HTTP, no sockets).
The producer writes an FTMO compliance status file each cycle derived from the
same frozen helpers the :class:`ComplianceDashboard` uses (``ftmo_levels`` +
``finite``): it presents the profile, official/internal daily & max loss levels,
and the remaining loss budgets for the latest account snapshot. It is purely
informational — it evaluates nothing and influences no trading decision.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from ..compliance.contract import finite, ftmo_levels


def compliance_status(compliance_config, account_snapshot, now):
    """A deterministic, candidate-free FTMO budget/level view. No side effects."""
    cfg = compliance_config
    profile = cfg.profile
    acct = account_snapshot if isinstance(account_snapshot, dict) else {}
    equity = finite(acct.get("equity"))
    levels = ftmo_levels(acct, profile, cfg.ftmo)

    status = {
        "kind": "compliance_status",
        "timestamp": serialize.iso_utc(now),
        "program": profile.program,
        "account_type": profile.account_type,
        "profile_verified": profile.profile_verified,
        "profile_error": profile.verification_error(),
        "account_currency": profile.account_currency,
        "initial_balance": profile.initial_balance,
        "day_start_balance": acct.get("day_start_balance"),
        "trading_day": acct.get("trading_day"),
        "equity": equity,
        "daily_anchor_conflict": bool(acct.get("daily_anchor_conflict")),
        "config_digest": cfg.digest(),
    }
    if levels is not None:
        status.update({
            "official_daily_level": levels["official_daily_level"],
            "internal_daily_level": levels["internal_daily_level"],
            "official_max_level": levels["official_max_level"],
            "internal_max_level": levels["internal_max_level"],
            "remaining_daily_loss_budget": (None if equity is None
                                            else equity - levels["internal_daily_level"]),
            "remaining_max_loss_budget": (None if equity is None
                                          else equity - levels["internal_max_level"]),
        })
    else:
        status.update({
            "official_daily_level": None, "internal_daily_level": None,
            "official_max_level": None, "internal_max_level": None,
            "remaining_daily_loss_budget": None, "remaining_max_loss_budget": None,
        })
    return status


def write_status(path, status):
    """Atomically write a status dict as canonical JSON."""
    atomic_write_text(path, serialize.canonical_json(status))
