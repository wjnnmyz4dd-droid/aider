"""Session Edge MT5 Execution Adapter (Phase 3).

The shipped adapter is the MQL5 Expert Advisor ``SessionEdgeExecutionEA.mq5``
(compiled and run inside a MetaTrader 5 terminal). This Python package is the
executable reference/specification and its test harness:

    execution_consumer.ExecutionConsumer  -- reference adapter (bridge consumer)
    mock_mt5.MockMT5                       -- programmable MT5 terminal double

The adapter is an EXECUTION ADAPTER ONLY: no strategy logic, no signal/trend/
risk calculation, no direction decisions, no networking. It consumes the
accepted Filesystem Execution Bridge (the single source of truth) and the MT5
trade API — nothing else.
"""

from __future__ import annotations

from .execution_consumer import ExecutionConsumer, XReason, normalize_symbol

__all__ = ["ExecutionConsumer", "XReason", "normalize_symbol"]
