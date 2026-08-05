"""Production entry point: ``python -m forex_swing_orb.manage`` (Phase 8D).

Builds the DEMO-ONLY autonomous stop-manager from validated environment/JSON
config and the live MT5-backed broker-truth source, then runs a graceful loop:
adopt open positions, evaluate tracked tickets, write a health status file, and
sleep. Graceful shutdown on SIGINT/SIGTERM. Refuses to start (non-zero exit) if
configuration is invalid, the FTMO profile is unusable, or the terminal is not
connected. The manager never places an order; every stop change routes through the
manage bridge to the EA. No networking beyond the injected MT5 client.
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone

from .service import ManagerService


class _Loop:
    def __init__(self, service):
        self.service = service
        self._stop = False

    def _handle(self, *_):
        self._stop = True

    def _install_signals(self):
        try:
            signal.signal(signal.SIGINT, self._handle)
            signal.signal(signal.SIGTERM, self._handle)
        except (ValueError, AttributeError):
            pass                          # not on the main thread / no SIGTERM

    def run(self, max_cycles=None):
        self._install_signals()
        cadence = float(getattr(self.service, "_cadence_sec", 900))
        n = 0
        while not self._stop:
            now = datetime.now(timezone.utc)
            try:
                self.service.run_once(now)
            except Exception as exc:                    # never crash the loop
                self.service._last_error = repr(exc)
            n += 1
            if max_cycles is not None and n >= max_cycles:
                break
            time.sleep(max(1.0, cadence))


def _preflight(service):
    """Demo-safety startup gate: the broker truth must be reachable and connected."""
    truth = getattr(service, "_truth", None)
    if truth is None or not truth.terminal_connected():
        raise RuntimeError("MT5 terminal not connected")


def main(argv=None):
    try:
        service = ManagerService.build_from_env()
        _preflight(service)
    except Exception as exc:                            # fail closed on any startup error
        print(f"manager startup refused: {exc}", file=sys.stderr)
        return 2
    _Loop(service).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
