"""Performance category (ADR-031 SS10): 28 pairs, sub-250ms cycle."""

from __future__ import annotations

import time
import unittest

from phantom.risk_engine.config import RiskEngineConfig
from phantom.risk_engine.models import PortfolioState
from phantom.runtime.engine import RuntimeOrchestrator
from phantom.runtime.models import CycleOutcome, TradingWindow
from phantom.runtime.profiles import make_custom_profile
from tests.phantom.runtime._fixtures import (
    T0,
    make_account_state,
    make_bars,
    make_config,
    make_market_safety_inputs,
    make_stub_bridge_submit,
    make_stub_compliance_engine,
    make_stub_evidence_engine,
    make_stub_mi_engine,
    make_stub_risk_engine,
    make_stub_strategy_engine,
)

_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]


class TestPerformance(unittest.TestCase):
    def test_28_pairs_complete_well_under_budget(self):
        orchestrator = RuntimeOrchestrator(
            make_config(), make_stub_evidence_engine(), make_stub_mi_engine(), make_stub_strategy_engine(),
            make_stub_risk_engine(), make_stub_compliance_engine(), make_stub_bridge_submit(),
        )
        profile = make_custom_profile(
            profile_id="perf", description="perf test", trading_window=TradingWindow(0, 24),
            session_rules=(), risk_profile=RiskEngineConfig(), allowed_pairs=tuple(_PAIRS * 4)[:28],
        )
        bars = make_bars()
        market_safety = make_market_safety_inputs()
        account_state = make_account_state()

        start = time.monotonic()
        records = [
            orchestrator.run_cycle_for_pair(
                pair, bars, (), 1.0, 1.0, market_safety, PortfolioState(), None, account_state, profile, T0, f"CYCLE-{i}",
            )
            for i, pair in enumerate(profile.allowed_pairs)
        ]
        elapsed_ms = (time.monotonic() - start) * 1000.0

        self.assertLess(elapsed_ms, 250.0, f"28-pair cycle took {elapsed_ms:.1f}ms, expected under 250ms")
        self.assertTrue(all(r.outcome != CycleOutcome.FAILED for r in records))


if __name__ == "__main__":
    unittest.main()
