"""SAFE, read-only Session Edge news-acquisition ownership diagnostic.

    python -m forex_swing_orb.runtime.recover
    python -m forex_swing_orb.runtime.recover --lock "<path to calendar_acq.lock>"

Answers the one operator question behind the Windows "another acquisition instance
is running" report: *is a LIVE Session Edge news process actually holding the lock
right now, or is this only a harmless leftover artifact?* It does so by
NON-DESTRUCTIVELY probing the OS lock (try-acquire, then immediately release) --
the same authority the service uses.

It is deliberately incapable of the dangerous "recovery" operators reach for:
it does NOT taskkill python.exe, does NOT kill ANY process, does NOT delete or
overwrite a lock file, and does NOT bypass any safety gate. A leftover lock never
needs manual deletion -- a dead owner's OS lock is already freed by the kernel, so
a normal restart self-heals. This command just makes that state visible.

Exit codes: 0 = no live owner (safe to start / will self-heal);
3 = a LIVE owner holds the lock (do not start a second); 2 = UNKNOWN (fail closed);
4 = usage/config error.
"""

from __future__ import annotations

import argparse
import sys

from ..newsfeed.acquisition_lock import AcquisitionOwnerState as S
from ..newsfeed.acquisition_lock import probe_ownership


def _resolve_lock_path(explicit):
    if explicit:
        return explicit
    # Fall back to the same validated calendar config the service uses (env/JSON),
    # which derives lock_file from the configured news output file.
    try:
        from ..newsfeed.config import load_calendar_config
        cfg = load_calendar_config()
        return cfg.lock_file
    except Exception:
        return None


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Read-only Session Edge news-acquisition ownership probe "
                    "(never kills a process or deletes a lock).")
    p.add_argument("--lock", default=None,
                   help="path to the news-acquisition lock file (default: derived "
                        "from SESSION_EDGE_CALENDAR_LOCK_FILE / the news output file).")
    args = p.parse_args(argv)

    lock_path = _resolve_lock_path(args.lock)
    if not lock_path:
        print("recover: no acquisition lock path configured; pass --lock <path> or set "
              "SESSION_EDGE_CALENDAR_LOCK_FILE / SESSION_EDGE_CALENDAR_OUTPUT_FILE.",
              file=sys.stderr)
        return 4

    state, detail = probe_ownership(lock_path)
    print("=" * 60)
    print(" SESSION EDGE — NEWS ACQUISITION OWNERSHIP PROBE (read-only)")
    print("=" * 60)
    print(f" Lock file          : {detail.get('lock_path', lock_path)}")
    print(f" Ownership state    : {state}")
    if state == S.HELD_BY_OTHER:
        print(f" Holder identity    : {detail.get('holder') or 'unavailable'}")
        if not detail.get("holder"):
            print(f"   note             : {detail.get('holder_note', '')}")
        print("\n A LIVE Session Edge news process holds the lock. Do NOT start a "
              "second one.\n Stop the running Session Edge (or its newsfeed child) "
              "first; a normal\n shutdown or the launcher's kill-on-exit binding frees "
              "the lock automatically.\n Do NOT taskkill unrelated python.exe.")
        rc = 3
    elif state in (S.ACQUIRED, S.STALE_RECOVERED):
        if state == S.STALE_RECOVERED:
            print(f" Prior owner (stale): {detail.get('prior_owner') or 'unknown'}")
        print("\n No live owner holds the lock right now. It is SAFE to start Session "
              "Edge;\n any leftover lock artifact will self-heal on startup (no manual "
              "deletion needed).")
        rc = 0
    else:                                              # UNKNOWN / ERROR
        print(f" Reason             : {detail.get('reason')}")
        print("\n Ownership could NOT be determined — failing closed. Do not start "
              "until resolved.")
        rc = 2
    print("=" * 60)
    return rc


if __name__ == "__main__":               # pragma: no cover
    raise SystemExit(main())
