"""Session Edge runtime integration layer (Phase 8D) — DEMO-ONLY.

Turns a validated :class:`RuntimeConfig` into the live, autonomous producer and
manager services and their supporting adapters (broker-truth, broker-derived
slippage, position adoption, status files). Pure wiring over already-accepted
components; it reimplements no strategy, compliance, risk, PM, or bridge logic and
adds no networking beyond the injected MT5 client.
"""

from __future__ import annotations

from .config import ConfigError, RuntimeConfig, load_config, password_from_env
from .slippage import BridgeSlippageSource
from .truth import Mt5TruthSource
from . import adoption, status, wiring

__all__ = [
    "ConfigError", "RuntimeConfig", "load_config", "password_from_env",
    "BridgeSlippageSource", "Mt5TruthSource", "adoption", "status", "wiring",
]
