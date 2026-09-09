"""Deterministic restart recovery / reconciliation (spec §10).

Single pass — no polling, no networking. Uses the ONE shared SeenResolver and the
consumer's single terminal path. Crash-safe and posture-aware:

  * terminal evidence (result/archive/ledger) -> ADOPT it (no hook, no 2nd result)
  * conflicting evidence                       -> quarantine (fail closed)
  * non-terminal claimed, re-runnable hook     -> re-process (safe)
  * non-terminal claimed, execution hook       -> mark reconciliation-required
                                                  (never blindly resubmit)
"""

from __future__ import annotations

from . import serialize
from .contract import HookPosture, ReasonCode, ResultState
from .paths import INSTRUCTION_NAME_RE, is_safe_regular_file


def _clean_tmp(directory, audit, now):
    n = 0
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return 0
    for p in entries:
        if p.name.startswith(".") and p.name.endswith(".tmp"):
            try:
                p.unlink()
                n += 1
            except OSError:
                continue
    if n:
        audit.emit(serialize.iso_utc(now), "reconcile", "TMP_CLEANED",
                   detail={"dir": directory.name, "count": n})
    return n


def recover(consumer, now):
    """Run reconciliation using an existing Consumer. Returns a summary dict."""
    paths, audit = consumer.paths, consumer.audit
    summary = {"tmp_cleaned": 0, "pending_quarantined": 0, "claimed_adopted": 0,
               "claimed_reprocessed": 0, "claimed_reconciliation_required": 0,
               "claimed_quarantined": 0}

    for d in (paths.pending, paths.claimed, paths.results):
        summary["tmp_cleaned"] += _clean_tmp(d, audit, now)

    # pending files with an invalid basename -> quarantine
    for p in (sorted(paths.pending.iterdir()) if paths.pending.exists() else []):
        if p.name.startswith(".") and p.name.endswith(".tmp"):
            continue
        if not INSTRUCTION_NAME_RE.match(p.name):
            consumer._move_or_audit(p, paths.quarantine / p.name, now, "quarantine", None)
            audit.emit(serialize.iso_utc(now), "reconcile", ResultState.ERROR,
                       reason_code=ReasonCode.E_UNSAFE_PATH, detail={"pending": p.name})
            summary["pending_quarantined"] += 1

    # claimed files stranded by a crash
    for p in (sorted(paths.claimed.iterdir()) if paths.claimed.exists() else []):
        if p.name.startswith(".") and p.name.endswith(".tmp"):
            continue
        if not INSTRUCTION_NAME_RE.match(p.name) or not is_safe_regular_file(p, paths.root):
            consumer._move_or_audit(p, paths.quarantine / p.name, now, "quarantine", None)
            audit.emit(serialize.iso_utc(now), "reconcile", ResultState.ERROR,
                       reason_code=ReasonCode.E_UNSAFE_PATH, detail={"claimed": p.name})
            summary["claimed_quarantined"] += 1
            continue

        sid = p.name[:-5]
        seen = consumer.resolver.resolve(sid)
        if seen.conflict:
            consumer._quarantine(p, sid, now, ReasonCode.E_CONFLICT, detail=seen.detail)
            summary["claimed_quarantined"] += 1
        elif seen.terminal:
            consumer._adopt(sid, seen, now, action="reconcile")   # no hook, no 2nd result
            summary["claimed_adopted"] += 1
        elif consumer.hook_posture in HookPosture.RERUNNABLE:
            consumer.process(sid, now)                            # safe deterministic re-run
            summary["claimed_reprocessed"] += 1
        else:
            consumer.mark_reconciliation_required(sid, now)       # execution posture: no retry
            summary["claimed_reconciliation_required"] += 1

    audit.emit(serialize.iso_utc(now), "reconcile", "DONE", detail=summary)
    return summary
