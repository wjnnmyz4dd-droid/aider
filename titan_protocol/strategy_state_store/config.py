"""Configuration for the persisted ORB qualification-lockout store
(ADR-035 §18.A item 2, Phase 2 Step 2B)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STRATEGY_STATE_STORE_VERSION = "1.0.0"


@dataclass(frozen=True)
class StrategyStateStoreConfig:
    state_file: Path


__all__ = ["STRATEGY_STATE_STORE_VERSION", "StrategyStateStoreConfig"]
