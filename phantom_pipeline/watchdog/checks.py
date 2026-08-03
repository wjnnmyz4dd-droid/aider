"""Pure health-derivation, aggregation, and recovery-eligibility functions
(ADR-011 §5, §6, §7, §9).

Every function here is a pure function of its explicit arguments — no
I/O, no clock reads beyond an explicit `now` parameter, no state-store
access (that responsibility belongs to `engine.py`, which reads the store
once and passes plain values in here) — the same discipline
`position_manager.checks`/`compliance_engine.checks` already established.
Every component is evaluated independently, with no short-circuit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence, Tuple

from .config import WatchdogConfig
from .models import (
    LIFECYCLE_STATES,
    SEVERITY_RANK,
    ComponentHealth,
    ComponentSignal,
    HealthState,
    HeartbeatStatus,
)


def derive_heartbeat_status(
    component: str, last_seen_at: Optional[datetime], now: datetime, config: WatchdogConfig
) -> HeartbeatStatus:
    """Never observed (`last_seen_at is None`) is distinct from expired
    (observed once, then too old) — the former is `UNKNOWN`, the latter
    is "no heartbeat received" (ADR-011 §9), never conflated."""
    if last_seen_at is None:
        return HeartbeatStatus(component, None, 0, False, now)

    interval = config.heartbeat_interval_for(component)
    age = (now - last_seen_at).total_seconds()
    if age < 0:
        return HeartbeatStatus(component, last_seen_at, 0, False, now)

    missed_count = int(age // interval) if interval > 0 else 0
    expired = age > interval * config.heartbeat_max_age_multiplier
    return HeartbeatStatus(component, last_seen_at, missed_count, expired, now)


def derive_component_health(
    signal: ComponentSignal,
    heartbeat_status: HeartbeatStatus,
    recovering: bool,
    config: WatchdogConfig,
    now: datetime,
) -> ComponentHealth:
    """Combines this component's heartbeat-derived state with its own
    already-computed `reported_state` (if supplied) by taking the WORSE
    (higher-severity) of the two — never an average, never assuming the
    best case (ADR-011 §5).

    A lifecycle-phase `reported_state` (`STARTING`/`SHUTDOWN`) is passed
    through directly rather than combined by severity rank, per §6: these
    are not severity states, so "worse of X and STARTING" is not a
    meaningful comparison."""
    if signal.reported_state in LIFECYCLE_STATES:
        return ComponentHealth(
            signal.component, signal.kind, signal.reported_state, signal.detail or "lifecycle phase", now
        )

    if heartbeat_status.last_seen_at is None:
        heartbeat_state = HealthState.UNKNOWN
        heartbeat_reason = "no heartbeat ever observed"
    elif heartbeat_status.expired:
        heartbeat_state = HealthState.OFFLINE
        heartbeat_reason = "heartbeat expired (treated as no heartbeat received)"
    elif heartbeat_status.missed_count >= config.critical_missed_threshold:
        heartbeat_state = HealthState.CRITICAL
        heartbeat_reason = f"missed_count={heartbeat_status.missed_count} >= critical threshold"
    elif heartbeat_status.missed_count >= config.warning_missed_threshold:
        heartbeat_state = HealthState.WARNING
        heartbeat_reason = f"missed_count={heartbeat_status.missed_count} >= warning threshold"
    else:
        heartbeat_state = HealthState.HEALTHY
        heartbeat_reason = "heartbeat within expected interval"

    candidates = [(heartbeat_state, heartbeat_reason)]
    if signal.reported_state is not None:
        candidates.append((signal.reported_state, signal.detail or "reported by observed stage"))
    if recovering:
        candidates.append((HealthState.RECOVERING, "recovery action in progress"))

    state, reason = max(candidates, key=lambda pair: SEVERITY_RANK.get(pair[0], 4))
    return ComponentHealth(signal.component, signal.kind, state, reason, now)


def aggregate_overall_health(component_health: Sequence[ComponentHealth]) -> HealthState:
    """The worst (most severe) state across every monitored component
    (ADR-011 §5) — never an average or a majority vote. Lifecycle-phase
    states are excluded from the severity ladder (§6); if no component
    has entered the ladder yet, fail closed to `UNKNOWN` rather than
    assuming `HEALTHY` with no evidence."""
    if not component_health:
        return HealthState.UNKNOWN

    ladder_states = [c.state for c in component_health if c.state in SEVERITY_RANK]
    if ladder_states:
        return max(ladder_states, key=lambda s: SEVERITY_RANK[s])

    if any(c.state == HealthState.STARTING for c in component_health):
        return HealthState.STARTING
    if all(c.state == HealthState.SHUTDOWN for c in component_health):
        return HealthState.SHUTDOWN
    return HealthState.UNKNOWN


def is_recovery_eligible(
    state: HealthState, frozen: bool, recovering: bool, attempts_in_window: int, last_attempt_at, now: datetime, config: WatchdogConfig
) -> Tuple[bool, str]:
    """A pure eligibility gate, mirroring `position_manager.checks`'s
    gate/rule separation: this function decides only WHETHER recovery may
    be attempted; `engine.attempt_recovery` decides what happens next."""
    if frozen:
        return False, "frozen: exceeded bounded recovery attempts, awaiting human clear or a fresh healthy signal"
    if recovering:
        return False, "recovery already in progress for this component"
    if state in (HealthState.HEALTHY, HealthState.STARTING, HealthState.SHUTDOWN):
        return False, f"component is {state.value}, recovery not applicable"
    if attempts_in_window >= config.recovery_max_attempts:
        return False, f"attempts_in_window={attempts_in_window} >= recovery_max_attempts (bounded recovery, §7)"
    if last_attempt_at is not None:
        backoff = config.recovery_backoff_seconds * (attempts_in_window + 1)
        elapsed = (now - last_attempt_at).total_seconds()
        if elapsed < backoff:
            return False, f"backoff active, {backoff - elapsed:.3f}s remaining"
    return True, f"component is {state.value}, eligible for bounded recovery"
