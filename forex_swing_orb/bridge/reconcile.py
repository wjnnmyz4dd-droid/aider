"""Deterministic restart recovery / reconciliation (spec §10).

Single pass over the bridge tree — no polling, no networking. Recovers stray
temp files, quarantines corrupt/unsafe artifacts, finishes interrupted archival,
and safely re-processes claimed-but-not-terminal instructions. Never blindly
resubmits: an item already terminal in the ledger is archived, not re-run.
"""

from __future__ import annotations

from . import serialize
from .atomic import atomic_move
from .contract import ResultState
from .paths import INSTRUCTION_NAME_RE, instruction_name, is_safe_regular_file


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
    """Run reconciliation using an existing Consumer (its paths/ledger/audit/hook).
    Returns a deterministic summary dict."""
    paths, ledger, audit = consumer.paths, consumer.ledger, consumer.audit
    summary = {"tmp_cleaned": 0, "pending_quarantined": 0, "claimed_reprocessed": 0,
               "claimed_archived": 0, "claimed_quarantined": 0}

    # 1. stray temp files from interrupted writes (partial writes never visible)
    for d in (paths.pending, paths.claimed, paths.results):
        summary["tmp_cleaned"] += _clean_tmp(d, audit, now)

    # 2. pending files with an invalid basename -> quarantine
    for p in sorted(paths.pending.iterdir()) if paths.pending.exists() else []:
        if p.name.startswith(".") and p.name.endswith(".tmp"):
            continue
        if not INSTRUCTION_NAME_RE.match(p.name):
            atomic_move(p, paths.quarantine / p.name)
            audit.emit(serialize.iso_utc(now), "reconcile", ResultState.ERROR,
                       reason_code="E_UNSAFE_PATH", detail={"pending": p.name})
            summary["pending_quarantined"] += 1

    # 3. claimed files stranded by a crash
    for p in sorted(paths.claimed.iterdir()) if paths.claimed.exists() else []:
        if p.name.startswith(".") and p.name.endswith(".tmp"):
            continue
        if not INSTRUCTION_NAME_RE.match(p.name) or not is_safe_regular_file(p, paths.root):
            atomic_move(p, paths.quarantine / p.name)
            audit.emit(serialize.iso_utc(now), "reconcile", ResultState.ERROR,
                       reason_code="E_UNSAFE_PATH", detail={"claimed": p.name})
            summary["claimed_quarantined"] += 1
            continue
        sid = p.name[:-5]
        seen = ledger.get(sid)
        if seen is not None:
            # already terminal: finish the interrupted archive move, do NOT re-run
            dest = paths.archive_accepted if seen.get("state") == ResultState.ACCEPTED \
                else paths.archive_rejected
            atomic_move(p, dest / instruction_name(sid))
            audit.emit(serialize.iso_utc(now), "reconcile", "ARCHIVED",
                       reason_code=seen.get("state"), signal_id=sid)
            summary["claimed_archived"] += 1
        else:
            # not terminal: safe deterministic re-process (transport is idempotent)
            consumer.process(sid, now)
            summary["claimed_reprocessed"] += 1

    audit.emit(serialize.iso_utc(now), "reconcile", "DONE", detail=summary)
    return summary
