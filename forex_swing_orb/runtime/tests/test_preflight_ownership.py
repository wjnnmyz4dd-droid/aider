"""Read-only preflight news-acquisition ownership parity check (Part E) + launcher
working-directory / git-independence guards (Parts J/P).

The preflight check must PREDICT the launcher's ownership blocker without keeping
ownership, deleting the lock, starting the newsfeed, or killing anything, and must
report a live owner accurately rather than as stale.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.runtime import preflight as P  # noqa: E402
from forex_swing_orb.newsfeed.acquisition_lock import (NewsAcquisitionLock,  # noqa: E402
                                                       acquire_ownership,
                                                       AcquisitionOwnerState as S)


def _cfg_env(monkeypatch, runtime_dir):
    # point the calendar config's derived lock path at our temp runtime dir
    monkeypatch.setenv("SESSION_EDGE_CALENDAR_OUTPUT_FILE",
                       str(Path(runtime_dir) / "news_bundle.json"))


def test_preflight_reports_pass_when_lock_free(tmp_path, monkeypatch):
    rt = tmp_path / "session_edge_runtime"; rt.mkdir()
    _cfg_env(monkeypatch, rt)
    name, status, detail = P._check_news_acquisition_ownership(cfg=None)
    assert status == P.PASS and "no live owner" in detail


def test_preflight_probe_releases_ownership(tmp_path, monkeypatch):
    rt = tmp_path / "session_edge_runtime"; rt.mkdir()
    _cfg_env(monkeypatch, rt)
    P._check_news_acquisition_ownership(cfg=None)          # probes (acquire+release)
    # ownership must be free afterwards -> we can acquire it now
    lock, state, _ = acquire_ownership(str(rt / "calendar_acq.lock"))
    assert lock is not None                                # probe did NOT keep ownership
    lock.release()


def test_preflight_reports_pass_and_no_interference_with_live_owner(tmp_path, monkeypatch):
    rt = tmp_path / "session_edge_runtime"; rt.mkdir()
    _cfg_env(monkeypatch, rt)
    owner = NewsAcquisitionLock(str(rt / "calendar_acq.lock")).acquire()   # live owner
    try:
        name, status, detail = P._check_news_acquisition_ownership(cfg=None)
        assert status == P.PASS and "live acquisition owner" in detail
        assert owner.held                                  # never displaced
    finally:
        owner.release()


def test_preflight_reports_fail_on_unknown(tmp_path, monkeypatch):
    rt = tmp_path / "session_edge_runtime"; rt.mkdir()
    _cfg_env(monkeypatch, rt)
    real = os.open
    def boom(path, *a, **k):
        if str(path).endswith("calendar_acq.lock"):
            e = OSError("Access is denied"); e.errno = 13; e.winerror = 5; raise e
        return real(path, *a, **k)
    monkeypatch.setattr(os, "open", boom)
    name, status, detail = P._check_news_acquisition_ownership(cfg=None)
    monkeypatch.setattr(os, "open", real)
    assert status == P.FAIL and "winerror=5" in detail    # surfaces the exact reason


def test_preflight_never_deletes_lock(tmp_path, monkeypatch):
    rt = tmp_path / "session_edge_runtime"; rt.mkdir()
    lf = rt / "calendar_acq.lock"
    lf.write_text("pid=1 host=x")                          # pre-existing marker
    _cfg_env(monkeypatch, rt)
    P._check_news_acquisition_ownership(cfg=None)
    assert lf.exists()                                     # probe never deletes the marker


# (read-only-surface of preflight.py is already asserted by the existing
#  test_install_preflight_manifest::test_preflight_is_readonly_no_trade_or_process_surface,
#  which scans paren-suffixed call tokens rather than prose.)


# --- Parts J/P: launcher self-locates; git not required ---------------------
def test_bat_self_locates_working_directory():
    bat = (REPO / "run_session_edge.bat").read_text()
    assert 'cd /d "%~dp0"' in bat                          # robust regardless of caller CWD


def test_no_runtime_git_dependency():
    import subprocess as _sub  # noqa: F401  (only to confirm launcher doesn't shell git)
    launcher = (REPO / "forex_swing_orb" / "runtime" / "launcher.py").read_text()
    for tok in ("rev-parse", "\"git\"", "'git'", "git rev-parse"):
        assert tok not in launcher
