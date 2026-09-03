"""Autonomous calendar-acquisition refresh service (Phase 9D-R1-R) — DATA ONLY.

A background loop that periodically acquires, validates (coverage/effective
freshness), normalizes, and atomically writes the news file the existing compliance
layer reads. Runs as its OWN process (separate from the producer), so acquisition
failure can never crash trading. Every failure is caught: it records the operational
status, PRESERVES last-known-good, and lets the existing compliance freshness rule
eventually block trading — it never fabricates data and has no trade authority.

Properties: configurable interval, bounded retries + capped backoff, clean SIGINT/
SIGTERM shutdown, health reporting, no busy loop, no overlapping refresh (single-
threaded), and a single-instance lock so a duplicate process cannot start. ``now_fn``
and ``sleep_fn`` are injected for deterministic tests.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from . import health as health_mod
from . import writer
from .acquire import CalendarAcquirer
from .acquisition_lock import AcquisitionOwnerState, acquire_ownership
from .contract import AcquisitionError, Reason

STARTUP_DIAGNOSTIC_SCHEMA = 1
STARTUP_DIAGNOSTIC_FILE = "startup_diagnostic.json"


def _utc_now():
    return datetime.now(timezone.utc)


def _configure_logging(log_path):
    logger = logging.getLogger("session_edge.calendar")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    # Always attach a stderr handler so critical startup diagnostics (esp. an
    # ownership refusal + its reason) are reliably visible in the Windows console,
    # instead of relying on Python's lastResort handler. Idempotent (guarded by a
    # marker attribute) so repeated construction in-process does not duplicate lines.
    if not any(getattr(h, "_session_edge_stderr", False) for h in logger.handlers):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh._session_edge_stderr = True
        logger.addHandler(sh)
    if log_path and not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        h = logging.FileHandler(log_path, encoding="utf-8")
        h.setFormatter(fmt)
        logger.addHandler(h)
    return logger


class CalendarAcquisitionService:
    def __init__(self, acquirer, cfg, *, now_fn=_utc_now, sleep_fn=time.sleep,
                 logger=None):
        self.acquirer = acquirer
        self.cfg = cfg
        self._now = now_fn
        self._sleep = sleep_fn
        self.logger = logger or _configure_logging(cfg.log_file)
        self.health = health_mod.HealthState(
            enabled=cfg.enabled, provider=cfg.provider, file_path=cfg.output_file,
            refresh_sec=cfg.refresh_sec)
        self._stop = False
        self._busy = False
        self._last_content_hash = None       # for content_changed diagnostics
        self.acquisition_owner = None        # AcquisitionOwnerState once startup runs

    # -- one refresh attempt (bounded retries; never raises) -----------------
    def refresh_once(self, now):
        if self._busy:
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
                self.logger.warning("acquisition failed (%s); last-known-good preserved",
                                    exc.reason)
                return False
            try:
                writer.write_bundle(self.cfg.output_file, bundle)
            except OSError as exc:
                self.health.record_failure(now_iso=now_iso, reason=Reason.WRITE_FAILED,
                                           next_refresh_iso=next_iso)
                self._write_health()
                self.logger.error("news-file write failed (%r); last-known-good preserved",
                                  exc)
                return False
            self._last_content_hash = bundle["provenance"].get("content_hash")
            self.health.record_success(now_iso=now_iso, bundle=bundle,
                                       next_refresh_iso=next_iso)
            self._write_health()
            self.logger.info("calendar refreshed: %d events (%d HIGH), as_of=%s, coverage=%s..%s",
                             bundle["provenance"]["event_count"],
                             bundle["provenance"]["high_event_count"], bundle["as_of"],
                             bundle["provenance"]["coverage_start"],
                             bundle["provenance"]["coverage_end"])
            return True
        finally:
            self._busy = False

    def _acquire_with_retries(self, now):
        # H4: the content-version lineage (content_hash + content_first_seen) comes
        # from the DURABLE last-known-good bundle on disk, so a restart cannot make
        # unchanged/stale content look freshly downloaded. In-memory hash is only a
        # diagnostic fallback.
        previous = writer.read_last_good(self.cfg.output_file)
        if previous is None and self._last_content_hash is not None:
            previous = self._last_content_hash
        attempts = self.cfg.retries + 1
        last = None
        for i in range(attempts):
            try:
                return self.acquirer.refresh(now, previous=previous)
            except AcquisitionError as exc:
                last = exc
                if i < attempts - 1:
                    self._sleep(min(self.cfg.backoff_sec * (2 ** i), 60.0))
        raise last

    def _runtime_dir(self):
        """The canonical Session Edge runtime directory (parent of the news bundle /
        lock), derived from the SAME config the ownership lock uses -- no new path
        authority. None if it cannot be resolved."""
        base = self.cfg.output_file or self.cfg.lock_file
        return str(Path(base).parent) if base else None

    def _write_startup_diagnostic(self, state, detail):
        """Persist an operator-readable startup-refusal diagnostic (Part B). Best-effort
        and diagnostic-ONLY: any failure here is swallowed and NEVER changes the
        fail-closed outcome. No secrets/credentials/env dump."""
        runtime_dir = self._runtime_dir()
        payload = {
            "schema_version": STARTUP_DIAGNOSTIC_SCHEMA,
            "timestamp": serialize.iso_utc(self._now()),
            "build_id": os.environ.get("SESSION_EDGE_BUILD_ID"),   # null if unset
            "gate": "NEWS_ACQUISITION_OWNERSHIP",
            "state": state,
            "operation": detail.get("operation"),
            "runtime_dir": runtime_dir,
            "lock_path": detail.get("lock_path"),
            "exception_class": detail.get("exception_class"),
            "errno": detail.get("errno"),
            "winerror": detail.get("winerror"),
            "message": detail.get("message") or detail.get("reason"),
            "holder": detail.get("holder"),                       # only for HELD_BY_OTHER
            "disposition": "FAIL_CLOSED",
        }
        try:
            if not runtime_dir:
                self.logger.error("startup diagnostic not written: runtime dir unresolved")
                return None
            path = Path(runtime_dir) / STARTUP_DIAGNOSTIC_FILE
            atomic_write_text(str(path), serialize.canonical_json(payload))
            self.logger.error("startup diagnostic written: %s", path)
            return str(path)
        except Exception as exc:                                  # never mask the refusal
            self.logger.error("could not write startup diagnostic (%r); refusal stands", exc)
            return None

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
            pass

    def _handle_signal(self, *_):
        self.logger.info("shutdown signal received; stopping after current refresh")
        self._stop = True

    def run_forever(self, max_cycles=None):
        """Refresh, then sleep the interval, repeatedly. Guarded by the canonical
        single-owner OS lock so at most one LIVE acquirer runs per domain. Self-
        healing: a dead owner's leftover lock never blocks startup; a live owner is
        never displaced; an unknown ownership outcome fails closed. No busy loop;
        clean shutdown. Returns the :class:`AcquisitionOwnerState` reached."""
        if not self.cfg.enabled:
            self.logger.info("calendar acquisition disabled; not starting")
            self.acquisition_owner = None
            return None

        lock, state, detail = (None, AcquisitionOwnerState.ACQUIRED, {})
        if self.cfg.lock_file:
            lock, state, detail = acquire_ownership(self.cfg.lock_file, logger=self.logger)
        self.acquisition_owner = state
        self.health.acquisition_owner = state

        if state in AcquisitionOwnerState.REFUSING:
            # Persist a deterministic, operator-readable diagnostic so a Windows
            # startup refusal never requires a screenshot. Diagnostic-ONLY: a failure
            # to write it can NEVER turn the refusal into permission (we still return
            # the REFUSING state below).
            self._write_startup_diagnostic(state, detail)
            if state == AcquisitionOwnerState.HELD_BY_OTHER:
                # Preserved message + explicit owner state. The live owner's health
                # artifact is left untouched (no mutation of an active owner's state).
                # A live owner is proven by the OS lock even when holder identity is
                # unavailable; surface the lock path and the note either way.
                self.logger.error("another acquisition instance is running; refusing to "
                                   "start (News Acquisition Owner: HELD_BY_OTHER; "
                                   "lock=%s; holder=%s%s)",
                                   detail.get("lock_path"), detail.get("holder"),
                                   "" if detail.get("holder")
                                   else " [" + str(detail.get("holder_note", "")) + "]")
            else:
                self.logger.error("news acquisition ownership could not be established "
                                  "(News Acquisition Owner: %s; %s); failing closed",
                                  state, detail.get("reason"))
            return state

        if state == AcquisitionOwnerState.STALE_RECOVERED:
            # Benign + expected on virtually every restart (the lock file is never
            # deleted on release); the OS lock was free, so no live owner was displaced.
            self.logger.info("news acquisition ownership acquired; reclaimed a leftover "
                             "ownership marker, no live owner (News Acquisition Owner: "
                             "STALE_RECOVERED — normal on restart)")
        else:
            self.logger.info("news acquisition ownership acquired "
                             "(News Acquisition Owner: ACQUIRED)")
        try:
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
        finally:
            if lock is not None:
                lock.release()               # graceful release; a crash frees via the OS
        return state

    def _sleep_interval(self):
        remaining = float(self.cfg.refresh_sec)
        while remaining > 0 and not self._stop:
            slice_s = min(remaining, 5.0)
            self._sleep(slice_s)
            remaining -= slice_s


def build_provider(cfg, *, now_fn=_utc_now, fetcher=None):
    if cfg.provider in ("forexfactory", "forexfactory_nextweek"):
        from .http_provider import ForexFactoryCalendarProvider
        window = "nextweek" if cfg.provider == "forexfactory_nextweek" else "thisweek"
        return ForexFactoryCalendarProvider(window=window, timeout=cfg.timeout_sec,
                                            fetcher=fetcher, now_fn=now_fn,
                                            max_response_bytes=cfg.max_response_bytes)
    if cfg.provider == "static":
        from .provider import StaticFileCalendarProvider
        return StaticFileCalendarProvider(cfg.source_file, trusted=cfg.static_trusted,
                                          now_fn=now_fn)
    raise AcquisitionError(Reason.CONFIG_ERROR, {"unknown_provider": cfg.provider})


def build_from_env(env=None, config_path=None, *, now_fn=_utc_now, sleep_fn=time.sleep,
                   fetcher=None):
    from .config import load_calendar_config
    cfg = load_calendar_config(env=env, config_path=config_path)
    provider = build_provider(cfg, now_fn=now_fn, fetcher=fetcher)
    acquirer = CalendarAcquirer(provider, cfg)
    return CalendarAcquisitionService(acquirer, cfg, now_fn=now_fn, sleep_fn=sleep_fn)
