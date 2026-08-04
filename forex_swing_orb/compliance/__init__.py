"""Deterministic FTMO Compliance Engine (Phase 5C) — FOREX-ONLY, FTMO-ONLY.

A mandatory, deterministic gate between the authoritative Session Edge strategy
and the Filesystem Bridge. No trade reaches the bridge without a COMPLIANCE_PASS.
No networking, no LLM authority, no wall clock (time injected), fail closed.
"""

from __future__ import annotations

from .contract import (ComplianceConfig, ComplianceDecision, Decision,
                       FtmoConfig, GateVerdict, NewsLockoutConfig, ReasonCode,
                       SessionConfig, Stage, SCHEMA_VERSION, ENGINE_VERSION,
                       validate_reason)
from .audit import ComplianceAuditLog
from .dashboard import ComplianceDashboard
from .engine import ComplianceEngine
from . import mapping

__all__ = [
    "ComplianceConfig", "ComplianceDecision", "Decision", "FtmoConfig",
    "GateVerdict", "NewsLockoutConfig", "ReasonCode", "SessionConfig", "Stage",
    "SCHEMA_VERSION", "ENGINE_VERSION", "validate_reason",
    "ComplianceAuditLog", "ComplianceDashboard", "ComplianceEngine", "mapping",
]
