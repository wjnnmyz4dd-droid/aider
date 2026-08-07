"""Autonomous calendar-acquisition refresh service (§7) — DATA ONLY.

A background loop that periodically acquires, validates, normalizes, and atomically
writes the news file the existing compliance layer already reads. It runs as its OWN
process (separate from the producer), so acquisition failure can never crash the
producer runner. Even in-process, every failure is caught: the service records
unhealthy, PRESERVES the last-known-good file, and lets the existing compliance
freshness rule eventually block trading — it never fabricates calendar data and has
no trade authority.

Properties: configurable interval, bounded retries + bounded backoff, clean
shutdown on SIGINT/SIGTERM, health reporting, no busy loop, no overlapping refresh
(single-threaded, sequential). ``now_fn`` and ``sleep_fn`` are injected for
deterministic tests.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta, timezone

from ..bridge import serialize
from . import health as health_mod
from . import writer
from .acquire import CalendarAcquirer
from .contract import AcquisitionError, Reason


def _utc_now():
    return datetime.now(timezone.utc)


def _configure_logging(log_path):
    logger = logging.getLogger("session_edge.calendar")
    logger.setLevel(logging.INFO)
    if log_path and not logger.handlers:
        h = logging.FileHandler(log_path, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


class CalendarAcquisitionService:
    """Owns the refresh loop around a :class:`CalendarAcquirer`."""

    def __init__(self, acquirer, cfg, *, now_fn=_utc_now, sleep_fn=time.sleep,
                 logger=None):
        self.acquirer = acquirer
        self.cfg = cfg
        self._now = now_fn
        self._sleep = sleep_fn
        self.logger = logger or _configure_logging(cfg.log_file)
        self.health = health_mod.HealthState(
            enabled=cfg.enabled, provider=cfg.provider, file_path=cfg.output_file)
        self._stop = False
        self._busy = False               # guards against overlapping refresh

    # -- one refresh attempt (bounded retries; never raises) -----------------
    def refresh_once(self, now):
        """Acquire + write once. Returns True on success. On failure records
        unhealthy, preserves the last-known-good file, and returns False. Never
        raises — a failure must not crash the loop or the producer."""
        if self._busy:                   # no overlapping refresh operations
            return False
        self._busy = True
        try:
            now_iso = serialize.iso_utc(now)
            next_iso = serialize.iso_utc(now + timedelta(seconds=self.cfg.refresh_sec))
            self.health.record_attempt(now_iso)
            try:
                bundle = self._acquire_with_retries(now)
            except AcquisitionError as exc:
                self.health.record_failure(now_iso=now_iso, reason=exc.reason,
                                           next_refresh_iso=next_iso)
                self._write_health()
                self.logger.warning("acquisition failed (last-known-good preserved): %s",
                                    exc.reason)
                return False
            try:
                writer.write_bundle(self.cfg.output_file, bundle)
            except OSError as exc:
                self.health.record_failure(now_iso=now_iso, reason=Reason.WRITE_FAILED,
                                           next_refresh_iso=next_iso)
                self._write_health()
                self.logger.error("news-file write failed (last-known-good preserved): %r",
                                  exc)
                return False
            self.health.record_success(now_iso=now_iso, bundle=bundle,
                                       next_refresh_iso=next_iso)
            self._write_health()
            self.logger.info("calendar refreshed: %d events, as_of=%s",
                             bundle["provenance"]["event_count"], bundle["as_of"])
            return True
        finally:
            self._busy = False

    def _acquire_with_retries(self, now):
        """Bounded retries with bounded (capped) backoff. Raises the last
        AcquisitionError if all attempts fail."""
        attempts = self.cfg.retries + 1
        last = None
        for i in range(attempts):
            try:
                return self.acquirer.refresh(now)
            except AcquisitionError as exc:
                last = exc
                if i < attempts - 1:
                    delay = min(self.cfg.backoff_sec * (2 ** i), 60.0)
                    self._sleep(delay)
        raise last

    def _write_health(self):
        if self.cfg.health_file:
            try:
                health_mod.write_health(self.cfg.health_file, self.health.to_dict())
            except (OSError, ValueError) as exc:
                self.logger.warning("health write failed: %r", exc)

    # -- autonomous loop -----------------------------------------------------
    def _install_signals(self):
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError):
            pass                          # not main thread / platform w/o SIGTERM

    def _handle_signal(self, *_):
        self.logger.info("shutdown signal received; stopping after current refresh")
        self._stop = True

    def run_forever(self, max_cycles=None):
        """Refresh, then sleep the configured interval, repeatedly. No busy loop:
        a single bounded sleep between refreshes; clean shutdown on signal."""
        if not self.cfg.enabled:
            self.logger.info("calendar acquisition disabled; not starting")
            return
        self._install_signals()
        self.logger.info("calendar acquisition service started (DEMO, data-only)")
        n = 0
        while not self._stop:
            self.refresh_once(self._now())
            n += 1
            if max_cycles is not None and n >= max_cycles:
                break
            self._sleep_interval()
        self.logger.info("calendar acquisition service stopped gracefully")

    def _sleep_interval(self):
        """Sleep the refresh interval in bounded slices so shutdown latency stays
        low (no busy-wait)."""
        remaining = float(self.cfg.refresh_sec)
        while remaining > 0 and not self._stop:
            slice_s = min(remaining, 5.0)
            self._sleep(slice_s)
            remaining -= slice_s


def build_provider(cfg, *, now_fn=_utc_now, fetcher=None):
    """Construct the configured provider (no silent selection). ``fetcher`` is an
    optional injected HTTP callable for the network provider (tests)."""
    if cfg.provider in ("forexfactory", "forexfactory_nextweek"):
        from .http_provider import ForexFactoryCalendarProvider
        window = "nextweek" if cfg.provider == "forexfactory_nextweek" else "thisweek"
        return ForexFactoryCalendarProvider(window=window, timeout=cfg.timeout_sec,
                                            fetcher=fetcher, now_fn=now_fn)
    if cfg.provider == "static":
        from .provider import StaticFileCalendarProvider
        return StaticFileCalendarProvider(cfg.source_file, trusted=cfg.static_trusted,
                                          now_fn=now_fn)
    raise AcquisitionError(Reason.CONFIG_ERROR, {"unknown_provider": cfg.provider})


def build_from_env(env=None, config_path=None, *, now_fn=_utc_now, sleep_fn=time.sleep,
                   fetcher=None):
    """Build a fully-wired :class:`CalendarAcquisitionService` from validated env/JSON
    configuration. Fails closed on invalid configuration."""
    from .config import load_calendar_config
    cfg = load_calendar_config(env=env, config_path=config_path)
    provider = build_provider(cfg, now_fn=now_fn, fetcher=fetcher)
    acquirer = CalendarAcquirer(provider, cfg)
    return CalendarAcquisitionService(acquirer, cfg, now_fn=now_fn, sleep_fn=sleep_fn)
