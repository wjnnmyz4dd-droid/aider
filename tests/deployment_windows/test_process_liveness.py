"""Tests for `config_loader.is_process_alive()` -- a verified production
defect fix (Final Release Hardening follow-up).

Root cause: `os.kill(pid, 0)`, the standard POSIX liveness probe, does
NOT behave the same way on Windows. CPython maps signal value 0 to
`CTRL_C_EVENT` there, which can only be delivered via
`GenerateConsoleCtrlEvent` to a process sharing the caller's console.
Titan Protocol's background process is always launched with
`CREATE_NEW_CONSOLE` (see `start.py`) specifically so it survives the
launching shell closing -- which means a later, separate `start.py`/
`stop.py`/`health_check.py` invocation never shares a console with it,
so `os.kill(pid, 0)` against it always raised OSError on Windows, and
every one of these scripts' old `_is_pid_alive`/`_pid_alive`/
`_existing_pid` helpers reported a perfectly healthy background process
as dead. This was reported live by an operator running the real
Windows release: `health_check.py` showed `runtime process alive: FAIL`
and overall `STATUS: FAILED` for a process that was, per its own
continuously-updating `health.json` and its own visibly-still-printing
console window, obviously still running.

These tests exercise the real POSIX code path directly (this sandbox is
Linux) and the Windows `tasklist`-based code path via a mocked
`subprocess.run` (since no real Windows machine is available here) --
together they cover both platform branches this function actually
contains."""

from __future__ import annotations

import subprocess
import sys
import time
import unittest
from unittest import mock

from ._fixtures import DEPLOYMENT_DIR  # ensures deployment_windows/ is on sys.path

from config_loader import is_process_alive


class TestPosixBranch(unittest.TestCase):
    def test_current_process_is_alive(self):
        import os
        self.assertTrue(is_process_alive(os.getpid()))

    def test_a_process_that_has_exited_is_not_alive(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        # Give the OS a moment to fully reap/release the pid on slower CI.
        for _ in range(20):
            if not is_process_alive(proc.pid):
                break
            time.sleep(0.05)
        self.assertFalse(is_process_alive(proc.pid))

    def test_an_implausibly_large_pid_is_not_alive(self):
        self.assertFalse(is_process_alive(2**30))


class TestWindowsBranchIsNotBrokenLikeOsKillWas(unittest.TestCase):
    """The real regression: confirms the Windows code path uses
    `tasklist`, never `os.kill(pid, 0)` -- and that it correctly reports
    a process as alive purely from `tasklist` output, without requiring
    the caller and target to share a console (the exact condition that
    made the old `os.kill(pid, 0)`-based checks always fail for Titan
    Protocol's `CREATE_NEW_CONSOLE`-launched background process)."""

    def test_pid_present_in_tasklist_output_is_alive(self):
        fake_result = subprocess.CompletedProcess(
            args=["tasklist"], returncode=0,
            stdout='"python.exe","12345","Console","1","50,000 K"\r\n',
        )
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", return_value=fake_result) as run_mock:
            self.assertTrue(is_process_alive(12345))
        run_mock.assert_called_once()
        args = run_mock.call_args[0][0]
        self.assertIn("tasklist", args)
        self.assertIn("/FI", args)

    def test_pid_absent_from_tasklist_output_is_not_alive(self):
        fake_result = subprocess.CompletedProcess(args=["tasklist"], returncode=0, stdout="INFO: No tasks match.\r\n")
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", return_value=fake_result):
            self.assertFalse(is_process_alive(99999))

    def test_tasklist_invocation_failure_is_not_alive_not_a_crash(self):
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", side_effect=OSError("tasklist not found")):
            self.assertFalse(is_process_alive(1))

    def test_never_calls_os_kill_on_windows(self):
        """The specific regression guard: os.kill(pid, 0) must never be
        reached on the Windows branch, since that was the entire bug."""
        fake_result = subprocess.CompletedProcess(args=["tasklist"], returncode=0, stdout='"python.exe","1","Console","1","1 K"\r\n')
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", return_value=fake_result), \
             mock.patch("os.kill", side_effect=AssertionError("os.kill must not be called on the Windows branch")):
            self.assertTrue(is_process_alive(1))


if __name__ == "__main__":
    unittest.main()
