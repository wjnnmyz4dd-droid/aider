"""Deterministic `execution_id` derivation for position-management
requests (ADR-008 §7 Amendment 1: "generated once per request by
Position Manager before it reaches this stage [MT5 Bridge]").

Reuses `data_pipeline.trace.make_trace_id` — the same shared,
"compute once, share the result" deterministic-id utility every prior
stage's own id derivation already reuses (Strategy Engine's
`make_candidate_id`, MT5 Bridge's own `make_execution_id` for opening
trades). A *new* adjustment for the same position (e.g. a trailing-stop
update) must get a *fresh* `execution_id` — never a duplicate of a prior
one for the same position (ADR-008 §7 Amendment 1) — so the id is
derived from `(position_id, action, now)` rather than `position_id`
alone: identical given identical inputs (including `now`), distinct
across genuinely different evaluation instants.
"""

from __future__ import annotations

from datetime import datetime

from ..data_pipeline.trace import make_trace_id
from .models import ManagementAction


def make_position_execution_id(position_id: str, action: ManagementAction, now: datetime) -> str:
    return make_trace_id("position_execution", position_id, action.value, now.isoformat())
