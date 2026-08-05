"""Session Edge Autonomous Producer Runner (Phase 7A) — DEMO-ONLY, FOREX-ONLY, FTMO-ONLY.

Pure orchestration over accepted components: live inputs -> frozen strategy ->
FTMO compliance -> filesystem bridge -> result ingestion -> audit/recovery. It
reimplements no strategy, compliance, news, risk, signal-id, or bridge logic;
it never places an order and never modifies a stop. No networking.
"""

from __future__ import annotations

from .contract import (CycleOutcome, CycleResult, InterfaceGap, RunnerConfig,
                       RunnerMode, RunnerReason, RunnerRefused)
from .providers import (AccountStateProvider, Bars, BrokerHealthProvider,
                        MarketDataProvider, NewsDataProvider, validate_account,
                        validate_bars)
from .strategy_adapter import StrategyAdapter, candidate_from_instruction, load_engine
from .runner import ProducerRunner
from .dashboard import RunnerDashboard
from .service import ProducerService
from . import scheduler, ingest

__all__ = [
    "RunnerConfig", "RunnerMode", "RunnerReason", "RunnerRefused", "InterfaceGap",
    "CycleOutcome", "CycleResult", "MarketDataProvider", "AccountStateProvider",
    "NewsDataProvider", "BrokerHealthProvider", "Bars", "validate_bars",
    "validate_account", "StrategyAdapter", "candidate_from_instruction",
    "load_engine", "ProducerRunner", "RunnerDashboard", "ProducerService",
    "scheduler", "ingest",
]
