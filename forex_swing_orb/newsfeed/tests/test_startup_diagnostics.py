"""Authorized Windows-startup DIAGNOSTIC hardening (Parts B/C/D).

Proves the new diagnostics ENRICH observability without changing ownership semantics:
UNKNOWN preserves exception class / errno / winerror / operation / lock_path; a
startup refusal writes a deterministic startup_diagnostic.json; a diagnostic-write
failure never turns a refusal into permission; the newsfeed logger has a stderr
handler; and ACQUIRED / STALE_RECOVERED / HELD_BY_OTHER are unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.newsfeed.acquisition_lock import (acquire_ownership,  # noqa: E402
                                                       probe_ownership,
                                                       NewsAcquisitionLock,
                                                       AcquisitionOwnerState as S)
from forex_swing_orb.newsfeed.config import CalendarConfig  # noqa: E402
from forex_swing_orb.newsfeed.contract import RawCalendar  # noqa: E402
from forex_swing_orb.newsfeed.acquire import CalendarAcquirer  # noqa: E402
from forex_swing_orb.newsfeed.provider import InjectableCalendarProvider  # noqa: E402
from forex_swing_orb.newsfeed.service import (CalendarAcquisitionService,  # noqa: E402
                                              _configure_logging, STARTUP_DIAGNOSTIC_FILE)

NOW = datetime(2024, 1, 10, 12, 0, tzinfo=timezone.utc)


def _win_open_failer(winerror, errno_, msg="Access is denied"):
    real = os.open
    def _boom(path, *a, **k):
        if str(path).endswith("calendar_acq.lock"):
            e = OSError(msg); e.errno = errno_; e.winerror = winerror; e.strerror = msg
            raise e
        return real(path, *a, **k)
    return real, _boom


# --- Part D: UNKNOWN preserves the underlying OS error ----------------------
def test_unknown_open_failure_preserves_exception_errno_winerror(tmp_path, monkeypatch):
    lf = tmp_path / "session_edge_runtime" / "calendar_acq.lock"
    lf.parent.mkdir(parents=True)
    real, boom = _win_open_failer(5, 13)
    monkeypatch.setattr(os, "open", boom)
    lock, state, detail = acquire_ownership(str(lf))
    monkeypatch.setattr(os, "open", real)
    assert lock is None and state == S.UNKNOWN
    assert detail["exception_class"] == "ProcessLockUnavailable"
    assert detail["errno"] == 13 and detail["winerror"] == 5
    assert detail["operation"] == "OPEN_LOCK_FILE"
    assert detail["lock_path"].endswith("calendar_acq.lock")


def test_unknown_no_lock_path_is_structured():
    lock, state, detail = acquire_ownership(None)
    assert state == S.UNKNOWN and detail["operation"] == "RESOLVE_LOCK_PATH"
    assert detail["errno"] is None and detail["winerror"] is None


# --- Part C: stderr handler is always attached ------------------------------
def test_logger_has_stderr_handler():
    logger = _configure_logging(None)
    assert any(getattr(h, "_session_edge_stderr", False) for h in logger.handlers)
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    # idempotent: no duplicate stderr handler on re-config
    n = sum(1 for h in logger.handlers if getattr(h, "_session_edge_stderr", False))
    _configure_logging(None)
    assert sum(1 for h in logger.handlers if getattr(h, "_session_edge_stderr", False)) == n


# --- Part B: startup_diagnostic.json on a refusal ---------------------------
def _svc(tmp_path, *, lock_file):
    out = tmp_path / "session_edge_runtime" / "news_bundle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = CalendarConfig(enabled=True, provider="static", output_file=str(out),
                         health_file=str(out.parent / "calendar_acq_status.json"),
                         refresh_sec=10, retries=0, backoff_sec=0, lock_file=lock_file)
    prov = InjectableCalendarProvider(
        lambda now: RawCalendar(source_name="t", source_identifier="t", provider_version="v",
                                fetched_at=NOW, events=(), source_as_of=NOW, complete=True,
                                trusted=True), trusted=True)
    return CalendarAcquisitionService(CalendarAcquirer(prov, cfg), cfg,
                                      now_fn=lambda: NOW, sleep_fn=lambda s: None), out


def test_startup_diagnostic_written_on_held_by_other(tmp_path):
    rt = tmp_path / "session_edge_runtime"; rt.mkdir()
    lf = rt / "calendar_acq.lock"
    holder = NewsAcquisitionLock(str(lf)).acquire()          # a live owner
    try:
        svc, out = _svc(tmp_path, lock_file=str(lf))
        state = svc.run_forever(max_cycles=1)
        assert state == S.HELD_BY_OTHER
        diag = rt / STARTUP_DIAGNOSTIC_FILE
        assert diag.exists()
        d = json.loads(diag.read_text())
        assert d["gate"] == "NEWS_ACQUISITION_OWNERSHIP"
        assert d["state"] == S.HELD_BY_OTHER and d["disposition"] == "FAIL_CLOSED"
        assert d["schema_version"] >= 1
    finally:
        holder.release()


def test_startup_diagnostic_written_on_unknown(tmp_path, monkeypatch):
    svc, out = _svc(tmp_path, lock_file=str(tmp_path / "session_edge_runtime" / "calendar_acq.lock"))
    real, boom = _win_open_failer(5, 13)
    monkeypatch.setattr(os, "open", boom)
    state = svc.run_forever(max_cycles=1)
    monkeypatch.setattr(os, "open", real)
    assert state == S.UNKNOWN
    diag = out.parent / STARTUP_DIAGNOSTIC_FILE
    d = json.loads(diag.read_text())
    assert d["state"] == S.UNKNOWN and d["winerror"] == 5 and d["errno"] == 13
    assert d["operation"] == "OPEN_LOCK_FILE" and d["disposition"] == "FAIL_CLOSED"
    # no secrets/credentials in the artifact
    blob = diag.read_text().lower()
    for secret in ("password", "token", "secret", "apikey", "api_key", "login="):
        assert secret not in blob


def test_diagnostic_write_failure_still_fails_closed(tmp_path, monkeypatch):
    # even if the diagnostic file write itself raises, the refusal state still stands
    # (the writer swallows the error internally and never turns refusal into permission).
    import forex_swing_orb.newsfeed.service as svc_mod
    svc, out = _svc(tmp_path, lock_file=str(tmp_path / "session_edge_runtime" / "calendar_acq.lock"))
    real, boom = _win_open_failer(5, 13)
    monkeypatch.setattr(os, "open", boom)                     # force UNKNOWN
    monkeypatch.setattr(svc_mod, "atomic_write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    try:
        state = svc.run_forever(max_cycles=1)                 # must not raise
    finally:
        monkeypatch.setattr(os, "open", real)
    assert state == S.UNKNOWN                                 # refusal not turned into permission


# --- semantics unchanged ----------------------------------------------------
def test_states_unchanged(tmp_path):
    lf = tmp_path / "acq.lock"
    l1, s1, _ = acquire_ownership(str(lf)); assert s1 == S.ACQUIRED; l1.release()
    l2, s2, _ = acquire_ownership(str(lf)); assert s2 == S.STALE_RECOVERED
    _, s3, _ = acquire_ownership(str(lf)); assert s3 == S.HELD_BY_OTHER   # live owner not stolen
    l2.release()
