"""The Position Manager (ADR-009).

`PositionManager.evaluate()` is the single entry point for one open
position's lifecycle evaluation: it always returns exactly one
`PositionManagementDecision` plus a `PositionUpdate` (§5), and
optionally a `PositionAdjustmentRequest`/`PositionCloseRequest` — never
submitted directly, always routed back through MT5 Bridge (Hard Rules,
§9). Every gate and rule in `checks.py` is evaluated independently, and
every one of them always runs — this task's own explicit instruction —
so `PositionManagementDecision.rule_evaluations` is always the complete
audit trail, never a partial one, mirroring `compliance_engine.engine`/
`execution_validator.engine`'s "no short-circuit" design.

**Action precedence** (highest to lowest, evaluated after all 5 gates
pass): `EMERGENCY_CLOSE` > `TIME_EXIT` > `PARTIAL_CLOSE` >
`MOVE_TO_BREAKEVEN` > `TRAIL_STOP` > `MOVE_STOP_LOSS` > `NO_ACTION`. This
ordering is this stage's own deterministic, documented policy — ADR-009
does not dictate a literal precedence, since real inputs could
plausibly satisfy more than one rule's trigger condition simultaneously
(e.g. break-even and partial-close both crossing their thresholds on the
same tick) and `PositionManagementDecision.action` is singular. Safety
first (emergency/time-based exits), then position-reduction (partial
close), then protection (break-even), then continuous adjustment
(trailing), then manual request (lowest, since it is the only
externally-driven rather than autonomously-triggered action).

Any gate that is `TRIGGERED` or `UNEVALUABLE` forces the overall action
to `NO_ACTION` (a "HOLD") regardless of what any rule concluded (§10
Hard Rule: "if synchronization cannot be restored, freeze
management... never guess") — **except** `COOLDOWN_ENFORCEMENT`, which
never throttles `EMERGENCY_CLOSE` (the ultimate safety valve; a
deliberate, documented exception, not dictated verbatim by ADR-009's
text). `MANAGEMENT_ELIGIBILITY`, `STALE_POSITION_DETECTION`,
`SYNCHRONIZATION_VALIDATION`, and `DUPLICATE_MANAGEMENT_PREVENTION` all
apply uniformly, with no exception, even to `EMERGENCY_CLOSE` — freezing
management under genuine uncertainty is safer than acting on an
unreconciled or stale view, even under emergency pressure.

`evaluate()` never mutates any upstream object and never talks to MT5 —
all state lives in the injected `PositionManagerStateStore`, read fresh
each call via explicit parameters, so identical inputs (including
identical store state) always produce identical decisions (§11
determinism).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Union

from ..scanner.models import Direction
from . import checks
from .config import DEFAULT_CONFIG, POSITION_MANAGER_VERSION, PositionManagerConfig
from .execution_id import make_position_execution_id
from .logging_sink import (
    log_management_decision,
    log_position_update,
    log_rule_evaluation,
    log_synchronization_result,
)
from .metrics import PositionManagerMetrics
from .models import (
    SCHEMA_VERSION,
    LifecycleState,
    ManagementAction,
    PositionAdjustmentRequest,
    PositionCloseRequest,
    PositionManagementDecision,
    PositionSynchronizationResult,
    PositionUpdate,
    RuleStatus,
)
from .state_store import PositionManagerStateStore

_ONE_TIME_ACTIONS = (
    ManagementAction.MOVE_TO_BREAKEVEN,
    ManagementAction.PARTIAL_CLOSE,
    ManagementAction.TIME_EXIT,
    ManagementAction.EMERGENCY_CLOSE,
)

_NEXT_LIFECYCLE_STATE = {
    ManagementAction.MOVE_TO_BREAKEVEN: LifecycleState.PROTECTED,
    ManagementAction.TRAIL_STOP: LifecycleState.TRAILING,
    ManagementAction.PARTIAL_CLOSE: LifecycleState.SCALING,
    ManagementAction.TIME_EXIT: LifecycleState.CLOSING,
    ManagementAction.EMERGENCY_CLOSE: LifecycleState.CLOSING,
}

_ADJUSTMENT_ACTIONS = (ManagementAction.MOVE_TO_BREAKEVEN, ManagementAction.TRAIL_STOP, ManagementAction.MOVE_STOP_LOSS)
_CLOSE_ACTIONS = (ManagementAction.PARTIAL_CLOSE, ManagementAction.TIME_EXIT, ManagementAction.EMERGENCY_CLOSE)


class PositionManager:
    def __init__(
        self,
        state_store: PositionManagerStateStore,
        config: PositionManagerConfig = DEFAULT_CONFIG,
        metrics: Optional[PositionManagerMetrics] = None,
    ):
        self.state_store = state_store
        self.config = config
        self.metrics = metrics

    def evaluate(
        self,
        position_id: str,
        trace_id: str,
        direction: Direction,
        entry_price: float,
        lifecycle_state: LifecycleState,
        current_price: Optional[float],
        current_stop_loss: Optional[float],
        current_take_profit: Optional[float],
        opened_at: datetime,
        market_data_timestamp: Optional[datetime],
        broker_position_exists: Optional[bool],
        compliance_kill_switch_active: Optional[bool],
        now: datetime,
        requested_stop_loss: Optional[float] = None,
    ) -> Tuple[PositionManagementDecision, PositionUpdate, Optional[Union[PositionAdjustmentRequest, PositionCloseRequest]]]:
        already_protected = self.state_store.has_taken_one_time_action(position_id, ManagementAction.MOVE_TO_BREAKEVEN)
        already_partial_closed = self.state_store.has_taken_one_time_action(position_id, ManagementAction.PARTIAL_CLOSE)
        last_action_at = self.state_store.last_action_at(position_id)
        has_pending = self.state_store.has_pending_request(position_id)

        gate_evaluations = (
            checks.management_eligibility(lifecycle_state),
            checks.stale_position_detection(market_data_timestamp, now, self.config),
            checks.synchronization_validation(broker_position_exists),
            checks.cooldown_enforcement(last_action_at, now, self.config),
            checks.duplicate_management_prevention(has_pending),
        )
        rule_evaluations = (
            checks.break_even(lifecycle_state, direction, entry_price, current_price, already_protected, self.config),
            checks.trailing_stop(direction, entry_price, current_price, current_stop_loss, self.config),
            checks.stop_loss_adjustment(direction, current_price, current_stop_loss, requested_stop_loss),
            checks.partial_close(direction, entry_price, current_price, already_partial_closed, self.config),
            checks.time_exit(opened_at, now, self.config),
            checks.emergency_close(compliance_kill_switch_active),
        )
        evaluations = gate_evaluations + rule_evaluations
        for evaluation in evaluations:
            log_rule_evaluation(position_id, trace_id, evaluation)

        emergency_triggered = rule_evaluations[5].status == RuleStatus.TRIGGERED
        blocking_gates = [
            g
            for g in gate_evaluations
            if g.status != RuleStatus.NOT_TRIGGERED and not (emergency_triggered and g.rule == "COOLDOWN_ENFORCEMENT")
        ]

        if blocking_gates:
            action = ManagementAction.NO_ACTION
            decision_reason = "blocked_by:" + "+".join(sorted(g.rule for g in blocking_gates))
        else:
            action, decision_reason = self._select_action(rule_evaluations)

        request = None
        new_lifecycle_state = lifecycle_state
        if action != ManagementAction.NO_ACTION:
            execution_id = make_position_execution_id(position_id, action, now)
            if action in _ADJUSTMENT_ACTIONS:
                new_stop_loss = self._resolve_new_stop_loss(
                    action, direction, entry_price, current_price, current_stop_loss, requested_stop_loss
                )
                request = PositionAdjustmentRequest(
                    SCHEMA_VERSION, execution_id, trace_id, position_id, new_stop_loss, current_take_profit, now
                )
            elif action == ManagementAction.PARTIAL_CLOSE:
                request = PositionCloseRequest(
                    SCHEMA_VERSION, execution_id, trace_id, position_id, self.config.partial_close_fraction, now
                )
            elif action in (ManagementAction.TIME_EXIT, ManagementAction.EMERGENCY_CLOSE):
                request = PositionCloseRequest(SCHEMA_VERSION, execution_id, trace_id, position_id, 1.0, now)

            self.state_store.mark_pending(position_id)
            self.state_store.record_action(position_id, now)
            if action in _ONE_TIME_ACTIONS:
                self.state_store.record_one_time_action(position_id, action)
            new_lifecycle_state = _NEXT_LIFECYCLE_STATE.get(action, lifecycle_state)
            self.state_store.set_lifecycle_state(position_id, new_lifecycle_state)

        decision = PositionManagementDecision(
            schema_version=SCHEMA_VERSION,
            position_id=position_id,
            trace_id=trace_id,
            action=action,
            decision_reason=decision_reason,
            rule_evaluations=evaluations,
            timestamp=now,
            position_manager_version=POSITION_MANAGER_VERSION,
        )
        unrealized_pnl = (
            checks.favorable_distance(direction, entry_price, current_price)
            if current_price is not None
            else None
        )
        update = PositionUpdate(
            schema_version=SCHEMA_VERSION,
            position_id=position_id,
            trace_id=trace_id,
            lifecycle_state=new_lifecycle_state,
            unrealized_pnl=unrealized_pnl,
            current_price=current_price,
            timestamp=now,
        )

        log_management_decision(decision)
        log_position_update(update)
        if self.metrics is not None:
            self.metrics.record_action(action)
            self.metrics.record_lifecycle_state(new_lifecycle_state)
        return decision, update, request

    def resolve_synchronization(
        self,
        position_id: str,
        trace_id: str,
        broker_position_exists: bool,
        after_reconnect: bool,
        now: datetime,
    ) -> PositionSynchronizationResult:
        """Rebuilds Live Position State from Broker Position State (§8) —
        broker-side truth is always ground truth for reconciliation,
        never the reverse. Clears any pending-request flag, since a
        freshly-reconciled position has no request whose outcome is
        still genuinely unknown to this stage."""
        new_state = (
            LifecycleState.RECOVERED_AFTER_DISCONNECT if after_reconnect else LifecycleState.RECOVERED
        )
        self.state_store.set_lifecycle_state(position_id, new_state)
        self.state_store.resolve_pending(position_id)
        detail = (
            "rebuilt from broker-side truth after reconnect"
            if after_reconnect
            else "rebuilt from broker-side truth after detected discrepancy"
        )
        result = PositionSynchronizationResult(
            schema_version=SCHEMA_VERSION,
            position_id=position_id,
            trace_id=trace_id,
            lifecycle_state=new_state,
            broker_position_found=broker_position_exists,
            detail=detail,
            timestamp=now,
        )
        log_synchronization_result(result)
        if self.metrics is not None:
            self.metrics.record_lifecycle_state(new_state)
        return result

    def _select_action(self, rule_evaluations) -> Tuple[ManagementAction, str]:
        break_even_r, trailing_r, sl_adjust_r, partial_r, time_exit_r, emergency_r = rule_evaluations
        precedence = (
            (emergency_r, ManagementAction.EMERGENCY_CLOSE),
            (time_exit_r, ManagementAction.TIME_EXIT),
            (partial_r, ManagementAction.PARTIAL_CLOSE),
            (break_even_r, ManagementAction.MOVE_TO_BREAKEVEN),
            (trailing_r, ManagementAction.TRAIL_STOP),
            (sl_adjust_r, ManagementAction.MOVE_STOP_LOSS),
        )
        for evaluation, action in precedence:
            if evaluation.status == RuleStatus.TRIGGERED:
                return action, evaluation.detail
        return ManagementAction.NO_ACTION, "no_rule_triggered"

    def _resolve_new_stop_loss(
        self,
        action: ManagementAction,
        direction: Direction,
        entry_price: float,
        current_price: Optional[float],
        current_stop_loss: Optional[float],
        requested_stop_loss: Optional[float],
    ) -> Optional[float]:
        if action == ManagementAction.MOVE_TO_BREAKEVEN:
            buffer = self.config.breakeven_buffer
            return entry_price + buffer if direction == Direction.UP else entry_price - buffer
        if action == ManagementAction.TRAIL_STOP:
            if direction == Direction.UP:
                return current_price - self.config.trailing_distance
            return current_price + self.config.trailing_distance
        if action == ManagementAction.MOVE_STOP_LOSS:
            return requested_stop_loss
        return current_stop_loss
