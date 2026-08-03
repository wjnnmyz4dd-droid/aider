"""A real `RecoveryActionExecutor` performing bounded OS-level recovery
actions (ADR-011 §7, §15).

**Bounded, translation-only, no trading authority.** Every one of the 8
named `RecoveryActionType` values maps to exactly one real, narrowly
scoped mechanism below — never inline, ad-hoc process control, never a
broker credential, never anything reachable from a trading decision.
`WatchdogEngine.attempt_recovery` (this package's own `engine.py`) already
owns eligibility, bounded-attempt counting, backoff, and freeze-and-
escalate; this class only ever attempts the one action it is told to
attempt and reports `True`/`False` — it never raises for an ordinary
failure (the same contract `FakeRecoveryActionExecutor` already documents),
and it never decides *whether* recovery should be attempted.

**Why some actions are injectable callbacks.** `RECONNECT_DEPENDENCY`/
`REBUILD_CONNECTION` inherently mean "call back into whatever dependency
`component` names" (e.g. `MT5Bridge.reconnect()`) — but this package has
"zero imports from any other `phantom_pipeline` subpackage" (`engine.py`'s
own explicit, user-confirmed constraint), so it structurally cannot import
`MT5Bridge` or any other stage to call it directly. A per-component
callback, injected by whoever wires the whole system together (the one
place that legitimately holds references to every stage), is the only
way to implement these two actions without violating that constraint.
`CLEAR_STALE_HEARTBEAT` is included in the same injectable-callback group
for the same reason: clearing heartbeat history is `WatchdogStateStore`'s
data, and this executor is deliberately never handed a reference to the
engine's own state store (it is constructed and passed to `WatchdogEngine`
as a wholly separate collaborator, per `engine.py`'s constructor) — adding
that coupling would be a new cross-cutting dependency this task's "no new
business logic" boundary does not authorize.

`RESTART_SERVICE`/`RESTART_WORKER`/`RESTART_MONITORING` map to a real
`systemctl restart <unit>` (component -> unit name is caller-configured);
`RELOAD_CONFIGURATION` sends a real `SIGHUP` to a PID read from a
component-configured PID file; `ROTATE_LOGS` performs a real, bounded
local log rotation (rename current file to `.1`, suffixed by a UTC
timestamp, truncate never assumed — the running process reopens its own
log handle on its own schedule, this action only makes room for it to).
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
from datetime import datetime, timezone
from typing import Callable, Dict, Mapping, Optional, Sequence

from .models import RecoveryActionType
from .recovery_executor import RecoveryActionExecutor

logger = logging.getLogger(__name__)

_SERVICE_ACTIONS = (
    RecoveryActionType.RESTART_SERVICE,
    RecoveryActionType.RESTART_WORKER,
    RecoveryActionType.RESTART_MONITORING,
)
_CALLBACK_ACTIONS = (
    RecoveryActionType.RECONNECT_DEPENDENCY,
    RecoveryActionType.REBUILD_CONNECTION,
    RecoveryActionType.CLEAR_STALE_HEARTBEAT,
)


def _default_command_runner(command: Sequence[str], timeout_seconds: float) -> bool:
    try:
        result = subprocess.run(
            list(command), timeout=timeout_seconds, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class RealRecoveryActionExecutor(RecoveryActionExecutor):
    def __init__(
        self,
        service_units: Optional[Mapping[str, str]] = None,
        reload_pidfiles: Optional[Mapping[str, str]] = None,
        log_paths: Optional[Mapping[str, str]] = None,
        reconnect_callbacks: Optional[Mapping[str, Callable[[], bool]]] = None,
        command_runner: Callable[[Sequence[str], float], bool] = _default_command_runner,
        signal_sender: Callable[[int, int], None] = os.kill,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._service_units: Dict[str, str] = dict(service_units or {})
        self._reload_pidfiles: Dict[str, str] = dict(reload_pidfiles or {})
        self._log_paths: Dict[str, str] = dict(log_paths or {})
        self._reconnect_callbacks: Dict[str, Callable[[], bool]] = dict(reconnect_callbacks or {})
        self._command_runner = command_runner
        self._signal_sender = signal_sender
        self._timeout_seconds = timeout_seconds

    def execute(self, component: str, action: RecoveryActionType) -> bool:
        try:
            if action in _SERVICE_ACTIONS:
                return self._restart_service(component)
            if action in _CALLBACK_ACTIONS:
                return self._invoke_callback(component)
            if action == RecoveryActionType.ROTATE_LOGS:
                return self._rotate_log(component)
            if action == RecoveryActionType.RELOAD_CONFIGURATION:
                return self._reload_configuration(component)
        except Exception:
            logger.warning("recovery action %s failed for %s", action, component, exc_info=True)
            return False
        return False

    def _restart_service(self, component: str) -> bool:
        unit = self._service_units.get(component)
        if unit is None:
            return False
        return self._command_runner(["systemctl", "restart", unit], self._timeout_seconds)

    def _invoke_callback(self, component: str) -> bool:
        callback = self._reconnect_callbacks.get(component)
        if callback is None:
            return False
        return bool(callback())

    def _reload_configuration(self, component: str) -> bool:
        pidfile = self._reload_pidfiles.get(component)
        if pidfile is None:
            return False
        try:
            with open(pidfile, "r", encoding="utf-8") as handle:
                pid = int(handle.read().strip())
        except (OSError, ValueError):
            return False
        self._signal_sender(pid, signal.SIGHUP)
        return True

    def _rotate_log(self, component: str) -> bool:
        path = self._log_paths.get(component)
        if path is None or not os.path.exists(path):
            return False
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rotated_path = f"{path}.{timestamp}"
        shutil.move(path, rotated_path)
        with open(path, "a", encoding="utf-8"):
            pass
        return True


__all__ = ["RealRecoveryActionExecutor"]
