"""Scanner package (ADR-002) — Phase 1.

Consumes only Data Pipeline (ADR-013) outputs; never connects to MT5;
never performs strategy, scoring, compliance, or execution logic; produces
only `ScannerObservation` (ADR-002 §2, §3, §6).
"""

from __future__ import annotations

from .config import SCANNER_VERSION, DEFAULT_CONFIG, ScannerConfig, SessionWindow
from .metrics import ScannerMetrics
from .models import (
    SCHEMA_VERSION,
    DataQualityFlag,
    Direction,
    EqualLevel,
    LiquidityEvent,
    MarketPhase,
    RangeStructure,
    ScannerObservation,
    SessionState,
    StructuralSignal,
    StructureConfidence,
    StructureKind,
    StructureTrendState,
    SwingKind,
    SwingPoint,
    SwingSequenceType,
    TrendReading,
    VolatilityLabel,
    VolatilityState,
)
from .scanner import Scanner

__all__ = [
    "SCANNER_VERSION",
    "DEFAULT_CONFIG",
    "ScannerConfig",
    "SessionWindow",
    "ScannerMetrics",
    "SCHEMA_VERSION",
    "DataQualityFlag",
    "Direction",
    "EqualLevel",
    "LiquidityEvent",
    "MarketPhase",
    "RangeStructure",
    "ScannerObservation",
    "SessionState",
    "StructuralSignal",
    "StructureConfidence",
    "StructureKind",
    "StructureTrendState",
    "SwingKind",
    "SwingPoint",
    "SwingSequenceType",
    "TrendReading",
    "VolatilityLabel",
    "VolatilityState",
    "Scanner",
]
