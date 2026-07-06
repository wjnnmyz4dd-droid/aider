"""Pure gate and rule evaluation functions (ADR-009 §8, §10).

Every function here is a pure function of its explicit arguments — no
I/O, no clock reads beyond an explicit `now`/timestamp parameter, no
state-store access (that responsibility belongs to `engine.py`, which
reads the store once and passes plain values in here). This mirrors
`compliance_engine.checks`/`execution_validator.checks`'s discipline:
each gate/rule is independent, side-effect free, always evaluated (no
short-circuit), and combined by the caller.

**Gates** (`management_eligibility`, `stale_position_detection`,
`synchronization_validation`, `cooldown_enforcement`,
`duplicate_management_prevention`) each resolve to `RuleStatus.
TRIGGERED` or `UNEVALUABLE` to *block* management for this evaluation —
both treated identically as a block (ADR-009 §10 Hard Rule: "if
synchronization cannot be restored, freeze management... never guess").

**Rules** (`break_even`, `trailing_stop`, `stop_loss_adjustment`,
`partial_close`, `time_exit`, `emergency_close`) each resolve to
`TRIGGERED` only when their specific condition is met; `UNEVALUABLE`
contributes nothing to the final action (it does not, by itself, force
a HOLD — only a gate does).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..scanner.models import Direction
from .config import PositionManagerConfig
from .models import LifecycleState, RuleEvaluation, RuleStatus

_TERMINAL_STATES = (LifecycleState.CLOSED, LifecycleState.CLOSING)
_PROTECTED_OR_LATER = (
    LifecycleState.PROTECTED,
    LifecycleState.TRAILING,
    LifecycleState.SCALING,
    LifecycleState.CLOSING,
    LifecycleState.CLOSED,
)


def favorable_distance(direction: Direction, entry_price: float, current_price: float) -> Optional[float]:
    if direction == Direction.UP:
        return current_price - entry_price
    if direction == Direction.DOWN:
        return entry_price - current_price
    return None


# -- Gates ------------------------------------------------------------


def management_eligibility(lifecycle_state: LifecycleState) -> RuleEvaluation:
    if lifecycle_state in _TERMINAL_STATES:
        return RuleEvaluation(
            "MANAGEMENT_ELIGIBILITY", RuleStatus.TRIGGERED, f"position is {lifecycle_state.value}, not eligible"
        )
    return RuleEvaluation("MANAGEMENT_ELIGIBILITY", RuleStatus.NOT_TRIGGERED, "position is eligible for management")


def stale_position_detection(
    market_data_timestamp: Optional[datetime], now: datetime, config: PositionManagerConfig
) -> RuleEvaluation:
    if market_data_timestamp is None:
        return RuleEvaluation("STALE_POSITION_DETECTION", RuleStatus.UNEVALUABLE, "missing market data timestamp")
    if now.tzinfo is None or market_data_timestamp.tzinfo is None:
        return RuleEvaluation("STALE_POSITION_DETECTION", RuleStatus.UNEVALUABLE, "timestamp is not timezone-aware")
    age = (now - market_data_timestamp).total_seconds()
    if age < 0:
        return RuleEvaluation("STALE_POSITION_DETECTION", RuleStatus.UNEVALUABLE, "market data timestamp is in the future")
    if age > config.max_market_data_age_seconds:
        return RuleEvaluation(
            "STALE_POSITION_DETECTION", RuleStatus.TRIGGERED, f"market data age={age:.3f}s exceeds max"
        )
    return RuleEvaluation("STALE_POSITION_DETECTION", RuleStatus.NOT_TRIGGERED, f"market data age={age:.3f}s is fresh")


def synchronization_validation(broker_position_exists: Optional[bool]) -> RuleEvaluation:
    if broker_position_exists is None:
        return RuleEvaluation("SYNCHRONIZATION_VALIDATION", RuleStatus.UNEVALUABLE, "missing broker position state")
    if not broker_position_exists:
        return RuleEvaluation(
            "SYNCHRONIZATION_VALIDATION", RuleStatus.TRIGGERED, "broker does not show this position open"
        )
    return RuleEvaluation("SYNCHRONIZATION_VALIDATION", RuleStatus.NOT_TRIGGERED, "broker confirms position open")


def cooldown_enforcement(
    last_action_at: Optional[datetime], now: datetime, config: PositionManagerConfig
) -> RuleEvaluation:
    if last_action_at is None:
        return RuleEvaluation("COOLDOWN_ENFORCEMENT", RuleStatus.NOT_TRIGGERED, "no prior action recorded")
    if now.tzinfo is None or last_action_at.tzinfo is None:
        return RuleEvaluation("COOLDOWN_ENFORCEMENT", RuleStatus.UNEVALUABLE, "timestamp is not timezone-aware")
    elapsed = (now - last_action_at).total_seconds()
    if elapsed < 0:
        return RuleEvaluation("COOLDOWN_ENFORCEMENT", RuleStatus.UNEVALUABLE, "last action timestamp is in the future")
    if elapsed < config.cooldown_seconds:
        return RuleEvaluation(
            "COOLDOWN_ENFORCEMENT", RuleStatus.TRIGGERED, f"cooldown active, {config.cooldown_seconds - elapsed:.3f}s remaining"
        )
    return RuleEvaluation("COOLDOWN_ENFORCEMENT", RuleStatus.NOT_TRIGGERED, f"cooldown elapsed ({elapsed:.3f}s)")


def duplicate_management_prevention(has_pending_request: bool) -> RuleEvaluation:
    if has_pending_request:
        return RuleEvaluation(
            "DUPLICATE_MANAGEMENT_PREVENTION", RuleStatus.TRIGGERED, "a request is already pending for this position"
        )
    return RuleEvaluation("DUPLICATE_MANAGEMENT_PREVENTION", RuleStatus.NOT_TRIGGERED, "no request currently pending")


# -- Rules --------------------------------------------------------------


def break_even(
    lifecycle_state: LifecycleState,
    direction: Direction,
    entry_price: Optional[float],
    current_price: Optional[float],
    already_taken: bool,
    config: PositionManagerConfig,
) -> RuleEvaluation:
    if already_taken or lifecycle_state in _PROTECTED_OR_LATER:
        return RuleEvaluation("BREAK_EVEN", RuleStatus.NOT_TRIGGERED, "already protected (idempotent)")
    if entry_price is None or current_price is None:
        return RuleEvaluation("BREAK_EVEN", RuleStatus.UNEVALUABLE, "missing entry/current price")
    distance = favorable_distance(direction, entry_price, current_price)
    if distance is None:
        return RuleEvaluation("BREAK_EVEN", RuleStatus.UNEVALUABLE, f"cannot evaluate for direction={direction.value}")
    if distance >= config.breakeven_trigger_distance:
        return RuleEvaluation("BREAK_EVEN", RuleStatus.TRIGGERED, f"favorable_distance={distance} >= trigger")
    return RuleEvaluation("BREAK_EVEN", RuleStatus.NOT_TRIGGERED, f"favorable_distance={distance} < trigger")


def trailing_stop(
    direction: Direction,
    entry_price: Optional[float],
    current_price: Optional[float],
    current_stop_loss: Optional[float],
    config: PositionManagerConfig,
) -> RuleEvaluation:
    if entry_price is None or current_price is None:
        return RuleEvaluation("TRAILING_STOP", RuleStatus.UNEVALUABLE, "missing entry/current price")
    distance = favorable_distance(direction, entry_price, current_price)
    if distance is None:
        return RuleEvaluation("TRAILING_STOP", RuleStatus.UNEVALUABLE, f"cannot evaluate for direction={direction.value}")
    if distance < config.trailing_start_distance:
        return RuleEvaluation("TRAILING_STOP", RuleStatus.NOT_TRIGGERED, f"favorable_distance={distance} below trailing start")

    if direction == Direction.UP:
        proposed_stop = current_price - config.trailing_distance
        improves = current_stop_loss is None or proposed_stop > current_stop_loss
    else:
        proposed_stop = current_price + config.trailing_distance
        improves = current_stop_loss is None or proposed_stop < current_stop_loss

    if not improves:
        return RuleEvaluation("TRAILING_STOP", RuleStatus.NOT_TRIGGERED, "proposed stop does not improve on current (never moves against favor)")
    return RuleEvaluation("TRAILING_STOP", RuleStatus.TRIGGERED, f"proposed_stop={proposed_stop} improves on current")


def stop_loss_adjustment(
    direction: Direction,
    current_price: Optional[float],
    current_stop_loss: Optional[float],
    requested_stop_loss: Optional[float],
) -> RuleEvaluation:
    if requested_stop_loss is None:
        return RuleEvaluation("STOP_LOSS_ADJUSTMENT", RuleStatus.NOT_TRIGGERED, "no manual adjustment requested")
    if current_price is None:
        return RuleEvaluation("STOP_LOSS_ADJUSTMENT", RuleStatus.UNEVALUABLE, "missing current price")
    if direction == Direction.UP:
        correct_side = requested_stop_loss < current_price
    elif direction == Direction.DOWN:
        correct_side = requested_stop_loss > current_price
    else:
        return RuleEvaluation("STOP_LOSS_ADJUSTMENT", RuleStatus.UNEVALUABLE, f"cannot validate side for direction={direction.value}")
    if not correct_side:
        return RuleEvaluation("STOP_LOSS_ADJUSTMENT", RuleStatus.UNEVALUABLE, "requested stop-loss is on the wrong side of price")
    if requested_stop_loss == current_stop_loss:
        return RuleEvaluation("STOP_LOSS_ADJUSTMENT", RuleStatus.NOT_TRIGGERED, "no change from current stop-loss")
    return RuleEvaluation("STOP_LOSS_ADJUSTMENT", RuleStatus.TRIGGERED, f"requested_stop_loss={requested_stop_loss}")


def partial_close(
    direction: Direction,
    entry_price: Optional[float],
    current_price: Optional[float],
    already_taken: bool,
    config: PositionManagerConfig,
) -> RuleEvaluation:
    if already_taken:
        return RuleEvaluation("PARTIAL_CLOSE", RuleStatus.NOT_TRIGGERED, "partial close already taken")
    if entry_price is None or current_price is None:
        return RuleEvaluation("PARTIAL_CLOSE", RuleStatus.UNEVALUABLE, "missing entry/current price")
    distance = favorable_distance(direction, entry_price, current_price)
    if distance is None:
        return RuleEvaluation("PARTIAL_CLOSE", RuleStatus.UNEVALUABLE, f"cannot evaluate for direction={direction.value}")
    if distance >= config.partial_close_trigger_distance:
        return RuleEvaluation("PARTIAL_CLOSE", RuleStatus.TRIGGERED, f"favorable_distance={distance} >= trigger")
    return RuleEvaluation("PARTIAL_CLOSE", RuleStatus.NOT_TRIGGERED, f"favorable_distance={distance} < trigger")


def time_exit(opened_at: Optional[datetime], now: datetime, config: PositionManagerConfig) -> RuleEvaluation:
    if opened_at is None:
        return RuleEvaluation("TIME_EXIT", RuleStatus.UNEVALUABLE, "missing opened_at")
    if now.tzinfo is None or opened_at.tzinfo is None:
        return RuleEvaluation("TIME_EXIT", RuleStatus.UNEVALUABLE, "timestamp is not timezone-aware")
    duration = (now - opened_at).total_seconds()
    if duration < 0:
        return RuleEvaluation("TIME_EXIT", RuleStatus.UNEVALUABLE, "opened_at is in the future")
    if duration >= config.max_duration_seconds:
        return RuleEvaluation("TIME_EXIT", RuleStatus.TRIGGERED, f"duration={duration:.3f}s >= max_duration_seconds")
    return RuleEvaluation("TIME_EXIT", RuleStatus.NOT_TRIGGERED, f"duration={duration:.3f}s within max")


def emergency_close(compliance_kill_switch_active: Optional[bool]) -> RuleEvaluation:
    if compliance_kill_switch_active is None:
        return RuleEvaluation("EMERGENCY_CLOSE", RuleStatus.UNEVALUABLE, "missing compliance kill-switch state")
    if compliance_kill_switch_active:
        return RuleEvaluation("EMERGENCY_CLOSE", RuleStatus.TRIGGERED, "compliance kill switch is active")
    return RuleEvaluation("EMERGENCY_CLOSE", RuleStatus.NOT_TRIGGERED, "compliance kill switch not active")
