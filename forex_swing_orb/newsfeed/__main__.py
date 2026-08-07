"""Entry point: run the autonomous calendar-acquisition service (DEMO, data-only).

    python -m forex_swing_orb.newsfeed

Builds the service from validated env/JSON configuration and runs the refresh loop.
This process ONLY acquires and writes the news file the existing compliance layer
reads; it has no trade authority and shares no state with the producer/manager
beyond that file.
"""

from __future__ import annotations

import sys

from .contract import AcquisitionError
from .service import build_from_env


def main(argv=None):
    try:
        service = build_from_env()
    except AcquisitionError as exc:
        sys.stderr.write(f"calendar acquisition config error: {exc}\n")
        return 2
    service.run_forever()
    return 0


if __name__ == "__main__":               # pragma: no cover
    raise SystemExit(main())
