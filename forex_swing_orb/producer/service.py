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


def write_health(health_path, dashboard, now, extra=None):
    """Atomically write the read-only status snapshot to a health file. ``extra`` is
    an optional dict merged in (e.g. producer writer-lock diagnostics)."""
    from ..bridge.atomic import atomic_write_text
    status = dashboard.status(now)
    if extra:
        status = {**status, **extra}
    atomic_write_text(health_path, serialize.canonical_json(status))


class ProducerService:
    """Background loop around :class:`ProducerRunner`. No console window required."""

    def __init__(self, runner, log_path, health_path, now_fn=_utc_now,
                 compliance_status_path=None, session_status_path=None, advisory=None,
                 writer_lock=None):
        self.runner = runner
        self.logger = configure_logging(log_path)
        self.health_path = health_path
        self.dashboard = RunnerDashboard(runner)
        self.compliance_status_path = compliance_status_path
        self.session_status_path = session_status_path
        self.advisory = advisory                 # Phase 9A ShadowAdvisoryService or None
        # F-3: single-writer authority for this account/entry-bridge domain. Held for
        # the whole service lifetime. None only in unit tests that drive the loop in
        # isolation; production always injects one via build_from_env.
        self.writer_lock = writer_lock
        self._now = now_fn
        self._stop = False

    def _lock_health(self):
        if self.writer_lock is None:
            return None
        return {"producer_lock_held": bool(self.writer_lock.held),
                "producer_lock_domain": str(self.writer_lock.domain)}

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
        # F-3: take single-writer authority BEFORE any market evaluation, compliance
        # authorization, or bridge write. A second producer on the same account/entry
        # bridge fails closed here and never reaches the loop below.
        self._acquire_writer_authority()
        now = self._now()
        self.runner.preflight(now)              # refuses (raises) if unsafe
        self._install_signals()
        self.logger.info("producer service started (DEMO)")
        write_health(self.health_path, self.dashboard, now, extra=self._lock_health())

    def _acquire_writer_authority(self):
        if self.writer_lock is None:
            return
        self.writer_lock.acquire()              # raises ProducerLockHeld/Unavailable -> fail closed
        self.logger.info("producer writer authority acquired: %s",
                         self.writer_lock.owner_diagnostics())

    def run_forever(self, max_cycles=None):
        """Deterministic closed-bar loop. Sleeps until the next exec-bar close."""
        self.start()
        try:
            n = 0
            while not self._stop:
                now = self._now()
                try:
                    self.runner.run_cycle(now)
                except Exception as exc:                       # never crash the service loop
                    self.runner._last_error = repr(exc)
                    self.logger.exception("cycle error")
                write_health(self.health_path, self.dashboard, now, extra=self._lock_health())
                self._write_compliance_status(now)
                self._write_session_status(now)
                self._observe_advisory(now)
                n += 1
                if max_cycles is not None and n >= max_cycles:
                    break
                self._sleep_until_next_bar(self._now())
        finally:
            self._release_writer_authority()
        self.logger.info("producer service stopped gracefully")

    def _release_writer_authority(self):
        if self.writer_lock is not None:
            self.writer_lock.release()
            self.logger.info("producer writer authority released")

    def _write_compliance_status(self, now):
        """Surface the FTMO compliance budget view as a read-only status file
        (no HTTP/sockets). Informational only; never influences trading."""
        if self.compliance_status_path is None:
            return
        try:
            from .. runtime.status import compliance_status, write_status
            acct = self.runner.account.snapshot(now)
            status = compliance_status(self.runner.config.compliance, acct, now)
            write_status(self.compliance_status_path, status)
        except Exception as exc:                            # never crash the loop
            self.logger.warning("compliance status write failed: %r", exc)

    def _write_session_status(self, now):
        """Write the canonical session snapshot to a read-only status file."""
        if self.session_status_path is None:
            return
        try:
            from ..bridge.atomic import atomic_write_text
            snap = getattr(self.runner, "_last_session_snapshot", None)
            if snap is not None:
                atomic_write_text(self.session_status_path, serialize.canonical_json(snap))
        except Exception as exc:
            self.logger.warning("session status write failed: %r", exc)

    def _observe_advisory(self, now):
        """Shadow-only advisory observation. Failure NEVER affects trading."""
        if self.advisory is None:
            return
        try:
            self.advisory.observe(self.runner, now)
        except Exception as exc:
            self.logger.warning("advisory shadow failed (non-blocking): %r", exc)

    def _sleep_until_next_bar(self, now):
        target = next_bar_close(now, self.runner.config.exec_timeframe)
        delay = max(1.0, (target - now).total_seconds())
        # cap a single sleep so shutdown latency stays bounded (no busy-wait)
        time.sleep(min(delay, float(self.runner.config.cadence_sec)))


def build_from_env(env=None, config_path=None, client=None, now_fn=_utc_now):
    """Construct a fully-wired, DEMO-ONLY :class:`ProducerService` from validated
    configuration and the live MT5-backed providers. Fails closed on any missing /
    invalid configuration or an unusable FTMO profile — never silently defaults a
    safety-relevant value.

    ``client`` is injected only by integration tests (a ``FakeMt5Client``); in
    production it is created from config via the live MT5 client factory.
    """
    from ..bridge.paths import BridgePaths
    from ..runtime import wiring
    from ..runtime.config import load_config
    from .runner import ProducerRunner

    cfg = load_config(env=env, config_path=config_path)
    cfg.ensure_runtime_dir()

    if client is None:                                  # pragma: no cover - real terminal
        client = wiring.build_client(cfg, env=env)

    compliance = wiring.build_compliance_config(cfg)    # raises if profile unusable
    runner_cfg = wiring.build_runner_config(cfg, compliance)
    paths = BridgePaths(cfg.bridge_root).ensure()

    runner = ProducerRunner(
        runner_cfg, bridge_paths=paths,
        market=wiring.build_market_provider(client, cfg),
        account=wiring.build_account_provider(client, cfg),
        news=wiring.build_news_provider(cfg),
        broker=wiring.build_broker_provider(client, cfg),
        strategy=wiring.build_strategy(cfg),                 # LONDON legacy fallback
        strategy_by_session=wiring.build_session_strategies(cfg),   # PR-4A per-session
        state_path=cfg.producer_state_path,
        runner_audit_path=cfg.runner_audit_path,
        compliance_audit_path=cfg.compliance_audit_path)

    advisory = None
    if cfg.advisory_enabled:
        from ..runtime.advisory import ShadowAdvisoryService
        advisory = ShadowAdvisoryService.build(cfg, client)

    # F-3: single-writer authority is keyed to the entry-bridge root (the writer
    # domain), so any two producers targeting the same bridge conflict regardless of
    # config-file spelling. No production flag can disable it.
    from .writer_lock import ProducerWriterLock
    writer_lock = ProducerWriterLock(paths.root)

    return ProducerService(
        runner, log_path=cfg.producer_log_path,
        health_path=cfg.producer_health_path, now_fn=now_fn,
        compliance_status_path=cfg.compliance_status_path,
        session_status_path=cfg.session_status_path, advisory=advisory,
        writer_lock=writer_lock)
