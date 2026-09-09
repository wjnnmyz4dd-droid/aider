"""Launcher child-lifetime binding (proc_group) + read-only recover diagnostic.

proc_group: on this (Linux) CI it must be a SAFE no-op so the launcher stays
platform-agnostic and POSIX behavior is unchanged; the Windows Job-Object
kill-on-close path is MANUAL WINDOWS VALIDATION. recover: a strictly read-only,
non-destructive ownership probe that never kills a process or deletes a lock file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.runtime import proc_group  # noqa: E402
from forex_swing_orb.runtime import recover  # noqa: E402
from forex_swing_orb.newsfeed.acquisition_lock import (NewsAcquisitionLock,  # noqa: E402
                                                       AcquisitionOwnerState as S)


def _code_only(path):
    """Source with ALL string literals (incl. docstrings) and comments removed, so a
    banned token is only found when it is real EXECUTABLE code, never prose."""
    import io
    import tokenize
    out = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT, tokenize.ENCODING):
                continue
            out.append(tok.string)
    return " ".join(out)


# --- proc_group ------------------------------------------------------------
def test_group_is_noop_and_safe_off_windows():
    g = proc_group.create_kill_on_close_group()
    if not sys.platform.startswith("win"):
        assert g.supported is False
    # assign()/close() never raise and never touch anything on the no-op path
    assert g.assign(None) in (False, True)            # False on no-op
    assert g.close() is None


def test_group_never_raises():
    # create must always return a group (never raise), so the launcher works anywhere
    g = proc_group.create_kill_on_close_group()
    assert hasattr(g, "assign") and hasattr(g, "close") and hasattr(g, "supported")


def test_proc_group_has_no_trade_or_kill_all_surface():
    code = _code_only(proc_group.__file__)
    for banned in ("taskkill", "order_send", "OrderSend", "TerminateProcess",
                   "gate_news", "subprocess"):
        assert banned not in code, f"proc_group must not call {banned!r}"
    # it kills ONLY via the OS Job Object (kill-on-close), never os.kill on a pid
    assert "os . kill" not in code and "kill (" not in code


# --- recover (read-only, non-destructive) ----------------------------------
def test_recover_reports_safe_when_no_live_owner(tmp_path, capsys):
    lf = tmp_path / "calendar_acq.lock"
    rc = recover.main(["--lock", str(lf)])
    assert rc == 0                                    # safe to start / self-heals
    out = capsys.readouterr().out
    assert "NEWS ACQUISITION OWNERSHIP PROBE" in out


def test_recover_reports_held_when_live_owner(tmp_path, capsys):
    lf = tmp_path / "calendar_acq.lock"
    held = NewsAcquisitionLock(str(lf)).acquire()
    try:
        rc = recover.main(["--lock", str(lf)])
        assert rc == 3                                # a live owner holds it
        assert "HELD_BY_OTHER" in capsys.readouterr().out
    finally:
        held.release()


def test_recover_is_non_destructive(tmp_path):
    # probing a live-held lock must NOT displace the owner nor delete the file
    lf = tmp_path / "calendar_acq.lock"
    held = NewsAcquisitionLock(str(lf)).acquire()
    try:
        recover.main(["--lock", str(lf)])
        assert lf.exists()                            # never deleted
        assert held.held                              # never displaced
        # a second probe still sees it held (owner intact)
        with pytest.raises(Exception):
            NewsAcquisitionLock(str(lf)).acquire()
    finally:
        held.release()
    # after the owner releases, recover reports safe again (rc 0)
    assert recover.main(["--lock", str(lf)]) == 0


def test_recover_usage_error_without_lock(monkeypatch, capsys):
    # no --lock and no calendar env config -> usage error (fail closed, rc 4)
    for var in ("SESSION_EDGE_CALENDAR_LOCK_FILE", "SESSION_EDGE_CALENDAR_OUTPUT_FILE",
                "SESSION_EDGE_NEWS_FILE", "SESSION_EDGE_CONFIG",
                "SESSION_EDGE_CALENDAR_ENABLED", "SESSION_EDGE_CALENDAR_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    rc = recover.main([])
    assert rc == 4


def test_recover_never_kills_or_deletes_in_source():
    code = _code_only(recover.__file__)
    for banned in ("taskkill", "unlink", "remove", "TerminateProcess", "terminate",
                   "rmtree", "subprocess", "Popen"):
        assert banned not in code, f"recover must be non-destructive; found {banned!r}"
    assert "os . kill" not in code and "kill (" not in code
