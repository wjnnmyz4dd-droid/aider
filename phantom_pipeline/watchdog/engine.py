"""The Watchdog (ADR-011).

`WatchdogEngine.evaluate()` is the read-only detection entry point: given
a batch of caller-supplied `ComponentSignal`s, it always returns exactly
one `SystemHealth` snapshot, evaluating every component independently
with no short-circuit (this ADR's own explicit instruction) — mirroring
`position_manager.engine`/`compliance_engine.engine`'s "always produce a
complete audit trail" discipline.

`WatchdogEngine.attempt_recovery()` is a SEPARATE, explicitly-invoked,
state-mutating method — mirroring `position_manager.engine`'s separation
of `evaluate()` from `resolve_synchronization()` — scoped to exactly the
8 named, bounded infrastructure actions in `RecoveryActionType` (ADR-011
§7). It never runs implicitly as a side effect of `evaluate()`: detection
and recovery are deliberately decoupled calls, so a caller can observe
health without ever triggering an action, and so recovery is always an
explicit, auditable decision by the caller (typically driven by
`checks.is_recovery_eligible`'s own eligibility gate, itself re-checked
inside `attempt_recovery`).

This package has zero imports from any other `phantom_pipeline`
subpackage (explicit, user-confirmed constraint) — every input is a
plain, caller-supplied value (`str`, `bool`, this package's own enums),
never an object imported from the stage being observed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence, Tuple

from . import alerting, checks
from .config import DEFAULT_CONFIG, WATCHDOG_VERSION, WatchdogConfig
from .logging_sink import log_alert, log_component_health, log_recovery_attempt
from .metrics import WatchdogMetrics
from .models import (
    SCHEMA_VERSION,
    Alert,
    AlertClass,
    ComponentHealth,
    ComponentSignal,
    HealthState,
    RecoveryActionType,
    RecoveryOutcome,
    RecoveryStatus,
    SystemHealth,
)
from .recovery_executor import RecoveryActionExecutor
from .state_store import WatchdogStateStore
from .trace import make_health_trace_id


class WatchdogEngine:
    def __init__(
        self,
        state_store: WatchdogStateStore,
        recovery_executor: RecoveryActionExecutor,
        config: WatchdogConfig = DEFAULT_CONFIG,
        metrics: Optional[WatchdogMetrics] = None,
    ):
        self.state_store = state_store
        self.recovery_executor = recovery_executor
        self.config = config
        self.metrics = metrics

    def record_heartbeat(self, component: str, now: datetime) -> None:
        """Records a liveness signal for `component` (ADR-011 §9). This
        is the only way heartbeat history is populated — `evaluate()`
        only reads it, never writes it, so identical inputs (including
        identical store state) always produce identical `SystemHealth`
        snapshots."""
        self.state_store.record_heartbeat(
            component, now, self.config.heartbeat_history_ttl_seconds, self.config.heartbeat_history_max_len
        )

    def evaluate(self, signals: Sequence[ComponentSignal], now: datetime) -> SystemHealth:
        component_healths = []
        heartbeat_statuses = []
        recovery_statuses = []

        for signal in signals:
            last_seen_at = self.state_store.last_heartbeat_at(signal.component)
            heartbeat_status = checks.derive_heartbeat_status(signal.component, last_seen_at, now, self.config)
            recovering = self.state_store.is_recovering(signal.component)
            health = checks.derive_component_health(signal, heartbeat_status, recovering, self.config, now)

            if health.state == HealthState.HEALTHY and self.state_store.is_frozen(signal.component):
                # A fresh, unambiguously-healthy signal observed directly
                # (not induced by the Watchdog's own recovery action)
                # clears a freeze (ADR-011 §8).
                self.state_store.clear_freeze(signal.component)

            self.state_store.record_state(signal.component, health.state, now)
            log_component_health(self._health_trace_id(now), health)
            if self.metrics is not None:
                self.metrics.record_component_state(signal.component, health.state)
                if heartbeat_status.last_seen_at is not None:
                    self.metrics.record_heartbeat_latency((now - heartbeat_status.last_seen_at).total_seconds())

            component_healths.append(health)
            heartbeat_statuses.append(heartbeat_status)
            recovery_statuses.append(
                RecoveryStatus(
                    component=signal.component,
                    in_progress=recovering,
                    frozen=self.state_store.is_frozen(signal.component),
                    last_action=self.state_store.last_action(signal.component),
                    last_outcome=self.state_store.last_outcome(signal.component),
                    attempts_in_window=self.state_store.attempts_in_window(
                        signal.component, now, self.config.recovery_window_seconds
                    ),
                    timestamp=now,
                )
            )

        overall = checks.aggregate_overall_health(component_healths)
        trace_id = self._health_trace_id(now, component_healths)
        return SystemHealth(
            schema_version=SCHEMA_VERSION,
            trace_id=trace_id,
            overall_health=overall,
            component_health=tuple(component_healths),
            heartbeat_statuses=tuple(heartbeat_statuses),
            recovery_statuses=tuple(recovery_statuses),
            timestamp=now,
            system_version=WATCHDOG_VERSION,
        )

    def attempt_recovery(
        self, component: str, action: RecoveryActionType, current_state: HealthState, now: datetime
    ) -> Tuple[RecoveryStatus, Optional[Alert]]:
        """Attempts one bounded recovery action for `component` (ADR-011
        §7). Re-checks eligibility itself — a caller cannot force an
        ineligible (frozen, already-recovering, or bound-exceeded)
        recovery attempt through this method."""
        frozen = self.state_store.is_frozen(component)
        recovering = self.state_store.is_recovering(component)
        attempts = self.state_store.attempts_in_window(component, now, self.config.recovery_window_seconds)
        last_attempt_at = self.state_store.last_attempt_at(component)
        eligible, reason = checks.is_recovery_eligible(
            current_state, frozen, recovering, attempts, last_attempt_at, now, self.config
        )

        if not eligible:
            status = RecoveryStatus(
                component=component,
                in_progress=recovering,
                frozen=frozen,
                last_action=self.state_store.last_action(component),
                last_outcome=self.state_store.last_outcome(component),
                attempts_in_window=attempts,
                timestamp=now,
            )
            log_recovery_attempt(self._health_trace_id(now), status, reason)
            return status, None

        self.state_store.set_recovering(component, True)
        self.state_store.record_recovery_attempt(component, now, self.config.recovery_window_seconds)
        succeeded = self.recovery_executor.execute(component, action)
        outcome = RecoveryOutcome.SUCCEEDED if succeeded else RecoveryOutcome.FAILED
        self.state_store.record_recovery_outcome(component, action, outcome)
        self.state_store.set_recovering(component, False)

        new_attempts = self.state_store.attempts_in_window(component, now, self.config.recovery_window_seconds)
        if outcome == RecoveryOutcome.FAILED and new_attempts >= self.config.recovery_max_attempts:
            self.state_store.freeze(component)

        status = RecoveryStatus(
            component=component,
            in_progress=False,
            frozen=self.state_store.is_frozen(component),
            last_action=action,
            last_outcome=outcome,
            attempts_in_window=new_attempts,
            timestamp=now,
        )
        detail = (
            f"recovery action {action.value} succeeded"
            if outcome == RecoveryOutcome.SUCCEEDED
            else f"recovery action {action.value} failed (attempt {new_attempts}/{self.config.recovery_max_attempts})"
        )
        log_recovery_attempt(self._health_trace_id(now), status, detail)
        if self.metrics is not None:
            self.metrics.record_recovery_attempt(component, outcome)

        alert = self._build_alert(component, AlertClass.RECOVERY, current_state, detail, now)
        return status, alert

    def clear_recovery_freeze(self, component: str) -> None:
        """An explicit human-operator action (ADR-011 §8) — the other of
        the two ways a freeze may be lifted, alongside `evaluate()`'s own
        automatic clear on a fresh directly-observed healthy signal."""
        self.state_store.clear_freeze(component)

    def generate_alerts(self, system_health: SystemHealth, now: datetime) -> Tuple[Alert, ...]:
        """Classifies every component in `system_health` into an alert
        (ADR-011 §11), applying escalation and deduplication. `SHUTDOWN`
        components are suppressed — the only condition under which an
        alert is suppressed, always deliberate and operator-visible."""
        alerts = []
        for health in system_health.component_health:
            base_class = alerting.classify_alert(health)
            if base_class is None:
                continue

            state_since = self.state_store.state_since(health.component)
            alert_class = (
                AlertClass.ESCALATION
                if alerting.should_escalate(health.component, health.state, state_since, now, self.config)
                else base_class
            )
            alert = self._build_alert(health.component, alert_class, health.state, health.reason, now)
            if alert is not None:
                alerts.append(alert)
        return tuple(alerts)

    def _build_alert(
        self, component: str, alert_class: AlertClass, severity: HealthState, detail: str, now: datetime
    ) -> Alert:
        last_signature = self.state_store.last_alert_signature(component, alert_class)
        repeat_count = alerting.resolve_repeat_count(detail, last_signature, now, self.config)
        alert = Alert(
            schema_version=SCHEMA_VERSION,
            trace_id=self._health_trace_id(now),
            component=component,
            alert_class=alert_class,
            severity=severity,
            detail=detail,
            repeat_count=repeat_count,
            timestamp=now,
        )
        self.state_store.record_alert(component, alert_class, detail, now, repeat_count)
        log_alert(alert)
        return alert

    @staticmethod
    def _health_trace_id(now: datetime, component_healths: Sequence[ComponentHealth] = ()) -> str:
        parts = [now.isoformat()] + [f"{c.component}:{c.state.value}" for c in component_healths]
        return make_health_trace_id(*parts)
