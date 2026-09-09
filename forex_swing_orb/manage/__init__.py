"""Session Edge live Position-Management channel (Phase 7B-B, Option C).

An additive, deterministic, filesystem-only stop-management channel between the
accepted Python PositionManager and the MQL5 EA. Reuses the frozen PM arithmetic
(``forex_swing_orb/position``) and the bridge serializer/atomic primitives; adds
no networking and no second broker-control path. DEMO-ONLY, FOREX-ONLY, FTMO-ONLY.
"""

from __future__ import annotations

from .contract import (ManageAction, ManageStatus, SCHEMA_VERSION,
                       build_instruction, build_result, compute_manage_id,
                       initial_r_digest, validate_instruction)
from .paths import ManagePaths, instruction_name, result_name
from .ledger import ManageLedger
from .producer import write_manage_instruction, ManageProducerError
from .consumer import ManageConsumer
from .adapter import BridgeMt5Adapter
from .service import ManagerService
from .outcome import OutcomeReconciler
from . import ticks

__all__ = [
    "ManageAction", "ManageStatus", "SCHEMA_VERSION", "build_instruction",
    "build_result", "compute_manage_id", "initial_r_digest", "validate_instruction",
    "ManagePaths", "instruction_name", "result_name", "ManageLedger",
    "write_manage_instruction", "ManageProducerError", "ManageConsumer",
    "BridgeMt5Adapter", "ManagerService", "OutcomeReconciler", "ticks",
]
