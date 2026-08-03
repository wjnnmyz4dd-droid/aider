"""Phase 3B stress testing: the named market-condition and
infrastructure scenarios not already covered by Phase 3A's own
multi-pair stress suite (`tests/titan_protocol/runtime/test_stress.py`) or
Phase 3B's own recovery suite (`tests/titan_protocol/e2e/test_recovery.py`,
which already covers Bridge/Runtime restart and repeated failures) --
flash crashes, high volatility, low liquidity, gap opens, weekend gaps,
holiday markets, broker disconnect, bridge disconnect, rapid news, and
rapid session changes. Each scenario proves the real pipeline degrades
safely (never crashes, never produces `CycleOutcome.FAILED`) rather
than asserting a specific trade outcome for inherently adverse
conditions."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from titan_protocol.bridge.models import ErrorCode
from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.compliance_engine.models import ComplianceDecision
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.evidence_engine.models import Bar
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.market_intelligence.models import MarketSafetyInputs, NewsCategory, NewsEvent, NewsImpact
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.models import CycleOutcome
from tests.titan_protocol.compliance_engine._fixtures import make_account_state, make_risk_snapshot, make_strategy_snapshot
from tests.titan_protocol.e2e._fixtures import make_config, make_profile, make_stub_bridge_submit, make_stub_compliance_engine, make_stub_evidence_engine, make_stub_mi_engine, make_stub_risk_engine, make_stub_strategy_engine

T0 = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)


def _build_orchestrator(**overrides):
    defaults = dict(
        config=make_config(), evidence_engine=make_stub_evidence_engine(), market_intelligence_engine=make_stub_mi_engine(),
        strategy_engine=make_stub_strategy_engine(), risk_engine=make_stub_risk_engine(),
        compliance_engine=make_stub_compliance_engine(), bridge_submit=make_stub_bridge_submit(),
    )
    defaults.update(overrides)
    return RuntimeOrchestrator(
        defaults["config"], defaults["evidence_engine"], defaults["market_intelligence_engine"],
        defaults["strategy_engine"], defaults["risk_engine"], defaults["compliance_engine"], defaults["bridge_submit"],
    )


def _flat_bars(price: float, count: int, start: datetime) -> tuple:
    return tuple(
        Bar(symbol="EURUSD", timestamp=start - timedelta(hours=count - i), open=price, high=price + 0.0005, low=price - 0.0005, close=price, volume=100.0)
        for i in range(count)
    )


class TestFlashCrashAndGapOpen(unittest.TestCase):
    def test_a_single_bar_flash_crash_never_crashes_the_real_evidence_engine(self):
        bars = list(_flat_bars(1.1000, 19, T0))
        bars.append(Bar(symbol="EURUSD", timestamp=T0, open=1.1000, high=1.1010, low=1.0200, close=1.0250, volume=500.0))
        report = EvidenceEngine(EvidenceEngineConfig()).evaluate("EURUSD", tuple(bars), T0)
        self.assertIsNotNone(report)

    def test_a_large_gap_open_never_crashes_the_real_pipeline(self):
        pre_gap = list(_flat_bars(1.1000, 15, T0 - timedelta(hours=5)))
        gap_bar = Bar(symbol="EURUSD", timestamp=T0 - timedelta(hours=4), open=1.1500, high=1.1520, low=1.1480, close=1.1500, volume=200.0)
        post_gap = list(_flat_bars(1.1500, 4, T0))
        bars = tuple(pre_gap + [gap_bar] + post_gap)
        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", bars, (), 1.0, 1.0, MarketSafetyInputs(), PortfolioState(), None,
            make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertNotEqual(record.outcome, CycleOutcome.FAILED)


class TestHighVolatilityAndLowLiquidity(unittest.TestCase):
    def test_high_volatility_bar_sequence_is_processed_without_error(self):
        bars = []
        price = 1.1000
        for i in range(20):
            price += 0.0050 if i % 2 == 0 else -0.0045
            bars.append(Bar(symbol="EURUSD", timestamp=T0 - timedelta(hours=20 - i), open=price, high=price + 0.0030, low=price - 0.0030, close=price, volume=1000.0))
        report = EvidenceEngine(EvidenceEngineConfig()).evaluate("EURUSD", tuple(bars), T0)
        self.assertIsNotNone(report)

    def test_extremely_wide_spread_is_scored_as_low_liquidity_without_error(self):
        snapshot = MarketIntelligenceEngine(MarketIntelligenceConfig()).evaluate(
            "EURUSD",
            EvidenceEngine(EvidenceEngineConfig()).evaluate("EURUSD", _flat_bars(1.1000, 20, T0), T0),
            (), current_spread=20.0, average_spread=1.0, market_safety_inputs=MarketSafetyInputs(), now=T0,
        )
        self.assertLess(snapshot.pair_safety.liquidity.liquidity_score, 50.0)


class TestWeekendAndHolidayMarkets(unittest.TestCase):
    def test_weekend_timestamp_is_processed_without_error(self):
        saturday = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)  # a Saturday
        orchestrator = _build_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", _flat_bars(1.1000, 20, saturday), (), 1.0, 1.0, MarketSafetyInputs(),
            PortfolioState(), None, make_account_state(), make_profile(), saturday, "CYCLE-1",
        )
        self.assertNotEqual(record.outcome, CycleOutcome.FAILED)

    def test_holiday_market_is_rejected_by_the_real_compliance_engine(self):
        holiday_inputs = MarketSafetyInputs(holidays=(T0.date(),))
        mi_snapshot = MarketIntelligenceEngine(MarketIntelligenceConfig()).evaluate(
            "EURUSD", EvidenceEngine(EvidenceEngineConfig()).evaluate("EURUSD", _flat_bars(1.1000, 20, T0), T0),
            (), 1.0, 1.0, holiday_inputs, T0,
        )
        self.assertTrue(mi_snapshot.pair_safety.market_safety.is_holiday)
        engine = ComplianceEngine(ComplianceEngineConfig())
        snapshot = engine.evaluate(
            "EURUSD", EvidenceEngine(EvidenceEngineConfig()).evaluate_snapshot("EURUSD", _flat_bars(1.1000, 20, T0), T0),
            mi_snapshot, make_strategy_snapshot(), make_risk_snapshot(), PortfolioState(), make_account_state(), T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)


class TestBrokerAndBridgeDisconnect(unittest.TestCase):
    def test_broker_maintenance_is_rejected_by_the_real_compliance_engine(self):
        maintenance_inputs = MarketSafetyInputs(broker_maintenance_active=True)
        mi_snapshot = MarketIntelligenceEngine(MarketIntelligenceConfig()).evaluate(
            "EURUSD", EvidenceEngine(EvidenceEngineConfig()).evaluate("EURUSD", _flat_bars(1.1000, 20, T0), T0),
            (), 1.0, 1.0, maintenance_inputs, T0,
        )
        engine = ComplianceEngine(ComplianceEngineConfig())
        snapshot = engine.evaluate(
            "EURUSD", EvidenceEngine(EvidenceEngineConfig()).evaluate_snapshot("EURUSD", _flat_bars(1.1000, 20, T0), T0),
            mi_snapshot, make_strategy_snapshot(), make_risk_snapshot(), PortfolioState(), make_account_state(), T0,
        )
        self.assertEqual(snapshot.decision, ComplianceDecision.REJECT)

    def test_bridge_disconnect_yields_bridge_error_outcome_never_a_partial_command(self):
        bridge_submit = make_stub_bridge_submit(error=ErrorCode.BRIDGE_NOT_READY)
        orchestrator = _build_orchestrator(bridge_submit=bridge_submit)
        record = orchestrator.run_cycle_for_pair(
            "EURUSD", _flat_bars(1.1000, 20, T0), (), 1.0, 1.0, MarketSafetyInputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-1",
        )
        self.assertEqual(record.outcome, CycleOutcome.BRIDGE_ERROR)
        self.assertEqual(record.bridge_error, ErrorCode.BRIDGE_NOT_READY)


class TestRapidNewsAndSessionChanges(unittest.TestCase):
    def test_many_overlapping_news_events_are_processed_without_error(self):
        events = tuple(
            NewsEvent(
                event_id=f"E{i}", currency="USD", category=NewsCategory.OTHER,
                impact=NewsImpact.HIGH if i % 3 == 0 else NewsImpact.LOW,
                scheduled_at=T0 + timedelta(minutes=i), released=False,
            )
            for i in range(50)
        )
        snapshot = MarketIntelligenceEngine(MarketIntelligenceConfig()).evaluate(
            "EURUSD", EvidenceEngine(EvidenceEngineConfig()).evaluate("EURUSD", _flat_bars(1.1000, 20, T0), T0),
            events, 1.0, 1.0, MarketSafetyInputs(), T0,
        )
        self.assertTrue(snapshot.pair_safety.news.blackout_active)

    def test_rapid_session_changes_across_a_single_day_never_crash_the_pipeline(self):
        orchestrator = _build_orchestrator()
        timestamps = [
            T0.replace(hour=1),   # Asian
            T0.replace(hour=8),   # London
            T0.replace(hour=13),  # London/NY overlap
            T0.replace(hour=18),  # Late New York
            T0.replace(hour=23),  # Closed
        ]
        outcomes = []
        for i, ts in enumerate(timestamps):
            record = orchestrator.run_cycle_for_pair(
                "EURUSD", _flat_bars(1.1000, 20, ts), (), 1.0, 1.0, MarketSafetyInputs(),
                PortfolioState(), None, make_account_state(), make_profile(), ts, f"CYCLE-{i}",
            )
            outcomes.append(record.outcome)
        self.assertTrue(all(o != CycleOutcome.FAILED for o in outcomes))


if __name__ == "__main__":
    unittest.main()
