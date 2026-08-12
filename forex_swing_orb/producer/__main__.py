"""Production entry point: ``python -m forex_swing_orb.producer`` (Phase 8D).

Builds the DEMO-ONLY autonomous producer from validated environment/JSON config
and the live MT5-backed providers, then runs the deterministic closed-bar loop
with graceful shutdown (SIGINT/SIGTERM), a health status file, and an FTMO
compliance status file. Refuses to start (non-zero exit) if configuration is
invalid, the FTMO profile is unusable, or the account is not a connected DEMO
account. No networking beyond the injected MT5 client.
"""

from __future__ import annotations

import sys

from .contract import RunnerRefused
from .service import build_from_env
from .writer_lock import ProducerLockError, ProducerLockHeld


def main(argv=None):
    try:
        service = build_from_env()
    except Exception as exc:                       # fail closed on any startup error
        print(f"producer startup refused: {exc}", file=sys.stderr)
        return 2
    try:
        service.run_forever()
    except ProducerLockHeld as exc:                 # F-3: another producer owns this domain
        print(f"producer refused to run: {exc}. Another producer is already the "
              f"authoritative writer for this account/entry bridge; not starting a "
              f"second writer.", file=sys.stderr)
        return 4
    except ProducerLockError as exc:               # F-3: lock could not be established
        print(f"producer refused to run: writer authority could not be established "
              f"({exc}); failing closed.", file=sys.stderr)
        return 4
    except RunnerRefused as exc:                    # demo/FTMO safety gate
        print(f"producer refused to run: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
