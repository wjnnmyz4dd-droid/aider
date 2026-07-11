"""Phantom stop script (Python Deployment Manager).

Stops ONLY the single Phantom process recorded in state/phantom.pid --
never a broad "kill every python.exe," which would kill unrelated
processes too. Graceful shutdown first, bounded wait, then forced
termination only if graceful shutdown did not take effect in time.
Logs and state files are never deleted by this script (only the pid
file, once the process is confirmed stopped).

Platform note (disclosed, not hidden): on Windows there is no direct
stdlib equivalent of a POSIX SIGTERM that a console Python process
reliably catches via `signal.signal(signal.SIGTERM, ...)` -- `taskkill
/PID <pid>` (without /F) is Windows' own "ask nicely" mechanism, used
here as the graceful attempt; `taskkill /F /PID <pid>` is the bounded
forceful fallback. On POSIX, a real SIGTERM is sent, which start.py's
own signal handler catches for a clean shutdown.
"""

from __future__ import annotations

import argparse
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from config_loader import ConfigError, load_settings

_GRACEFUL_WAIT_SECONDS = 10.0
_POLL_INTERVAL_SECONDS = 0.5


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_python_process(pid: int) -> bool:
    """Refuses to touch a pid that isn't actually a Python process --
    guards against a stale pid file whose number has been reused by an
    unrelated process (e.g. after a reboot)."""
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            return str(pid) in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    else:
        comm_path = Path(f"/proc/{pid}/comm")
        if comm_path.exists():
            try:
                return "python" in comm_path.read_text().strip().lower()
            except OSError:
                return False
        return _pid_alive(pid)  # weaker guarantee, but never worse than assuming it's fine


def _graceful_stop(pid: int) -> None:
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)


def _force_stop(pid: int) -> None:
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


def run(config_path: Path) -> int:
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED: configuration error: {exc}", file=sys.stderr)
        return 2

    pid_file = settings.state_dir / "phantom.pid"
    if not pid_file.exists():
        print(f"No {pid_file} found -- Phantom does not appear to be running.")
        return 0

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        print(f"{pid_file} is empty/unreadable -- removing stale pid file.")
        pid_file.unlink(missing_ok=True)
        return 0

    if not _is_python_process(pid):
        print(
            f"pid {pid} in {pid_file} is not a running python process "
            "(stale pid file, likely from a previous reboot). Removing the "
            "stale pid file without touching any process."
        )
        pid_file.unlink(missing_ok=True)
        return 0

    print(f"Stopping Phantom (pid {pid}) -- graceful shutdown...")
    _graceful_stop(pid)

    elapsed = 0.0
    while elapsed < _GRACEFUL_WAIT_SECONDS:
        if not _pid_alive(pid):
            print(f"Phantom stopped gracefully after {elapsed:.1f}s.")
            pid_file.unlink(missing_ok=True)
            return 0
        time.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS

    print(f"Graceful shutdown did not complete within {_GRACEFUL_WAIT_SECONDS}s -- forcing termination of pid {pid} only.")
    _force_stop(pid)
    time.sleep(1.0)
    if not _pid_alive(pid):
        print("Phantom force-stopped.")
        pid_file.unlink(missing_ok=True)
        return 0

    print(f"FAILED: pid {pid} is still running after a forced termination attempt. Investigate manually -- the pid file was NOT removed.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop the running Phantom deployment")
    parser.add_argument("--config", default=str(_HERE / "phantom.config.ini"))
    args = parser.parse_args()
    return run(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
