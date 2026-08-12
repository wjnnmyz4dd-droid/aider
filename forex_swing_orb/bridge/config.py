"""Session Edge Filesystem Execution Bridge — configuration.

Single, explicit config object. All values are data; there is no hidden default
that could weaken a security or validation gate. Filesystem-only; no networking.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeConfig:
    # Instruction schema versions the consumer accepts (spec §7-2 / §2.1 D1).
    # PR-4A: schema 2 adds a required ``session_id``; the London-only schema-1
    # instructions are retired from the multi-session pipeline (fail closed).
    schema_version_allowlist: frozenset = frozenset({2})
    # Known producers (spec §2.1 validation 4b).
    strategy_id_allowlist: frozenset = frozenset({"forex_swing_orb"})
    strategy_version_allowlist: frozenset = frozenset({"swing_orb.v1.4.0"})
    # File-size caps (spec §11); oversized files are quarantined unread past the cap.
    max_instruction_bytes: int = 65_536
    max_result_bytes: int = 65_536
    # A generated_timestamp more than this far in the future is implausible (skew).
    future_skew_tolerance_sec: int = 60
    # Canonical, filesystem-safe symbol form (e.g. EURUSD.FX). No raw '/' symbols.
    symbol_pattern: str = r"^[A-Z]{6}\.FX$"


DEFAULT_CONFIG = BridgeConfig()
