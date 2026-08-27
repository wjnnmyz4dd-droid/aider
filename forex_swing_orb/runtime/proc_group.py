"""Deterministic child-process lifetime binding for the launcher (Windows-focused).

Problem this solves: the launcher spawns the newsfeed/producer/manager as separate
processes. If the launcher dies ABNORMALLY on Windows -- the console window is
closed with the [X], the launcher is force-killed, or a fatal error skips the
``finally`` cleanup -- those children are ORPHANED and keep running. An orphaned
newsfeed child still holds the news-acquisition OS lock, so the next start
correctly (but frustratingly) reports ``HELD_BY_OTHER`` even though "the window is
closed", and the operator resorts to manual ``taskkill``.

Fix: put every child in a Windows **Job Object** created with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. The job handle is held by the launcher for
its lifetime; when the launcher process dies -- gracefully OR not -- the OS closes
that handle and terminates every process still in the job. No orphans, so a dead
Session Edge never blocks the next startup, and NO unrelated ``python.exe`` is ever
touched (only processes WE assigned to OUR job).

This module is ONLY child lifetime management: it acquires no trade authority,
reads no market data, and makes no ownership decision (the OS lock in
``bridge.process_lock`` remains the sole ownership authority). On non-Windows it is
a safe no-op group -- POSIX behavior is intentionally unchanged (the launcher's
existing terminate()+wait() reaping still runs), so nothing here alters the POSIX
pipeline.
"""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform.startswith("win")


class _NoopGroup:
    """POSIX / unsupported: no job. assign()/close() are safe no-ops so the launcher
    is platform-agnostic; POSIX cleanup stays with the launcher's terminate()+wait()."""

    supported = False

    def assign(self, proc):
        return False

    def close(self):
        return None


class _WindowsJobGroup:  # pragma: no cover - Windows only (cannot run in CI/Linux)
    """A Windows Job Object with kill-on-close; children assigned to it die when this
    group's handle is closed (explicitly, or by the OS when the launcher dies)."""

    supported = True

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._job = self._k32.CreateJobObjectW(None, None)
        if not self._job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION with LIMIT_KILL_ON_JOB_CLOSE (0x2000).
        class _BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IO(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _EXT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC),
                ("IoInfo", _IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _EXT()
        info.BasicLimitInformation.LimitFlags = 0x2000   # KILL_ON_JOB_CLOSE
        JobObjectExtendedLimitInformation = 9
        if not self._k32.SetInformationJobObject(
                self._job, JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            self.close()
            raise OSError(err, "SetInformationJobObject failed")

    def assign(self, proc):
        import ctypes
        handle = getattr(proc, "_handle", None)
        if not self._job or handle is None:
            return False
        ok = bool(self._k32.AssignProcessToJobObject(self._job, int(handle)))
        return ok

    def close(self):
        import ctypes
        job, self._job = getattr(self, "_job", None), None
        if job:
            self._k32.CloseHandle(job)   # kill-on-close terminates remaining children


def create_kill_on_close_group():
    """Return a child-lifetime group. On Windows, a real Job Object whose closure
    (explicit or on launcher death) kills all assigned children. On any other
    platform, or if the Job Object cannot be created, a safe no-op group (the
    launcher's own terminate()+wait() still reaps children on graceful exit).

    Never raises: a group is always returned so the launcher works everywhere."""
    if not _IS_WINDOWS:
        return _NoopGroup()
    try:                                              # pragma: no cover - Windows only
        return _WindowsJobGroup()
    except Exception:                                 # pragma: no cover - Windows only
        return _NoopGroup()                           # degrade to terminate()+wait()
