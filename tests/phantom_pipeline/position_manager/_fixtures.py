"""Shared test-only fixtures for the Position Manager test suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from phantom_pipeline.scanner.models import Direction

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=timezone.utc)
ENTRY_PRICE = 1.1000
POSITION_ID = "p1"
TRACE_ID = "t1"


def nominal_kwargs(**overrides):
    kwargs = dict(
        position_id=POSITION_ID,
        trace_id=TRACE_ID,
        direction=Direction.UP,
        entry_price=ENTRY_PRICE,
        lifecycle_state=None,  # must be supplied by caller
        current_price=ENTRY_PRICE,
        current_stop_loss=ENTRY_PRICE - 0.0050,
        current_take_profit=ENTRY_PRICE + 0.0100,
        opened_at=T0,
        market_data_timestamp=T0,
        broker_position_exists=True,
        compliance_kill_switch_active=False,
        now=T0 + timedelta(seconds=1),
    )
    kwargs.update(overrides)
    return kwargs
