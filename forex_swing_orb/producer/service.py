"""Service-friendly entry point (Phase 7A).

Provides a background-service-ready runner loop: file-based logging, a health
status file, graceful shutdown on SIGINT/SIGTERM, and a deterministic
closed-bar schedule (sleep until the next bar close — no busy-wait, no rapid
polling). The Windows service wrapper itself is NOT implemented here (out of
scope); the deployment contract is documented in the Phase 7A runbook.

DEMO-ONLY: ``preflight`` refuses to start on LIVE mode, an unverified FTMO
profile, a non-demo/unknown account, or unavailable inputs. No override flag
bypasses these protections.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from datetime import datetime, timezone

from ..bridge import serialize
from .dashboard import RunnerDashboard
from .scheduler import next_bar_close


def _utc_now():
    return datetime.now(timezone.utc)


def configure_logging(log_path):
    logger = logging.getLogger("session_edge.producer")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.FileHandler(log_path, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def write_health(health_path, dashboard, now):
    """Atomically write the read-only status snapshot to a health file."""
    from ..bridge.atomic import atomic_write_text
    atomic_write_text(health_path, serialize.canonical_json(dashboard.status(now)))


class ProducerService:
    """Background loop around :class:`ProducerRunner`. No console window required."""

    def __init__(self, runner, log_path, health_path, now_fn=_utc_now):
        self.runner = runner
        self.logger = configure_logging(log_path)
        self.health_path = health_path
        self.dashboard = RunnerDashboard(runner)
        self._now = now_fn
        self._stop = False

    def _install_signals(self):
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError):
            pass                     # not on the main thread / platform w/o SIGTERM

    def _handle_signal(self, *_):
        self.logger.info("shutdown signal received; finishing current cycle")
        self._stop = True

    def start(self):
        now = self._now()
        self.runner.preflight(now)              # refuses (raises) if unsafe
        self._install_signals()
        self.logger.info("producer service started (DEMO)")
        write_health(self.health_path, self.dashboard, now)

    def run_forever(self, max_cycles=None):
        """Deterministic closed-bar loop. Sleeps until the next exec-bar close."""
        self.start()
        n = 0
        while not self._stop:
            now = self._now()
            try:
                self.runner.run_cycle(now)
            except Exception as exc:                       # never crash the service loop
                self.runner._last_error = repr(exc)
                self.logger.exception("cycle error")
            write_health(self.health_path, self.dashboard, now)
            n += 1
            if max_cycles is not None and n >= max_cycles:
                break
            self._sleep_until_next_bar(self._now())
        self.logger.info("producer service stopped gracefully")

    def _sleep_until_next_bar(self, now):
        target = next_bar_close(now, self.runner.config.exec_timeframe)
        delay = max(1.0, (target - now).total_seconds())
        # cap a single sleep so shutdown latency stays bounded (no busy-wait)
        time.sleep(min(delay, float(self.runner.config.cadence_sec)))


def build_from_env():   # pragma: no cover - real deployment wiring is a later phase
    raise NotImplementedError(
        "Live provider wiring (MT5-backed market/account, approved news adapter) "
        "is out of scope for Phase 7A. Inject providers explicitly.")
