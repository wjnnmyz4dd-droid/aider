"""ADR-033 SS7 end-to-end proof: a real `RuntimeOrchestrator.run_cycle_for_pair()`
call driven entirely by data that passed through the actual
`MarketDataIngestionEngine`/`NewsIngestionEngine` pipelines -- not
directly-constructed `Bar`/`NewsEvent` objects. Every other test in
`tests/titan_protocol/market_data_ingestion/` and
`tests/titan_protocol/news_ingestion/` proves each package correctly in
isolation; this file is the one place that proves the seam ADR-033 SS0
actually promised: ingestion output is consumed by the frozen pipeline
with zero adaptation at the call site, exactly the same way
`tests/titan_protocol/runtime/test_integration.py`'s directly-built `Bar`
tuples are."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from titan_protocol.compliance_engine.config import ComplianceEngineConfig
from titan_protocol.compliance_engine.engine import ComplianceEngine
from titan_protocol.evidence_engine.config import EvidenceEngineConfig
from titan_protocol.evidence_engine.engine import EvidenceEngine
from titan_protocol.market_data_ingestion.config import MarketDataIngestionConfig
from titan_protocol.market_data_ingestion.engine import MarketDataIngestionEngine
from titan_protocol.market_data_ingestion.models import RawBar, TickEvent, Timeframe
from titan_protocol.market_intelligence.config import MarketIntelligenceConfig
from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
from titan_protocol.news_ingestion.config import NewsIngestionConfig
from titan_protocol.news_ingestion.engine import NewsIngestionEngine
from titan_protocol.news_ingestion.models import ProviderName
from titan_protocol.risk_engine.config import RiskEngineConfig
from titan_protocol.risk_engine.engine import RiskEngine
from titan_protocol.risk_engine.models import PortfolioState
from titan_protocol.runtime.config import RuntimeConfig
from titan_protocol.runtime.engine import RuntimeOrchestrator
from titan_protocol.runtime.models import CycleOutcome
from titan_protocol.strategy_engine.config import StrategyEngineConfig
from titan_protocol.strategy_engine.engine import StrategyEngine
from titan_protocol.strategy_engine.models import StrategyId, TradeIntent

from tests.titan_protocol.news_ingestion._fixtures import FakeProvider, make_normalized_event
from tests.titan_protocol.runtime._fixtures import (
    T0,
    make_account_state,
    make_market_safety_inputs,
    make_profile,
    make_stub_bridge_submit,
)

_SYMBOL = "EURUSD"
_TIMEFRAME = Timeframe.H1


def _ramp(a: float, b: float, n: int):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def _trending_prices():
    """The same double-bottom/double-top consolidation followed by a
    monotonic staircase uptrend as `tests.titan_protocol.runtime._fixtures.
    make_trending_bars()` -- reused here as a plain price list (rather
    than importing that helper directly) because this file needs raw
    prices to build `RawBar`s, not the already-normalized `Bar`s that
    helper returns."""
    prices = []
    low, high = 1.1000, 1.1050
    prices += _ramp(low, high, 6)
    prices += _ramp(high, low, 6)[1:]
    prices += _ramp(low, high, 6)[1:]
    prices += _ramp(high, low, 6)[1:]

    price = prices[-1]
    for _leg in range(4):
        for _ in range(8):
            price += 0.0020
            prices.append(price)
        for _ in range(4):
            price -= 0.0008
            prices.append(price)
    return prices


def _ingest_trending_bars(engine: MarketDataIngestionEngine, start: datetime = T0) -> None:
    prices = _trending_prices()
    n = len(prices)
    for i, p in enumerate(prices):
        bar_open_time = start - timedelta(hours=n - i)
        raw = RawBar(
            symbol=_SYMBOL, timeframe=_TIMEFRAME,
            broker_timestamp=bar_open_time, source_timestamp=bar_open_time, bar_open_time=bar_open_time,
            open=p, high=p + 0.0005, low=p - 0.0005, close=p, volume=100.0,
            is_closed=True, sequence_number=i,
        )
        result = engine.ingest_bar(raw, now=start)
        assert result.accepted, f"bar {i} unexpectedly rejected: {result.rejection_reason}"


class _MarketIntelligenceSpy:
    """Forwards to the real `MarketIntelligenceEngine.evaluate()` --
    every computation is genuine -- and just remembers the last snapshot
    it returned. `RuntimeAuditRecord` only carries a rendered summary
    *string* of the Market Intelligence result
    (`market_intelligence_summary`), not the structured snapshot itself,
    so this is the only way to assert on a real field (like
    `pair_safety.news.blackout_active`) without weakening the test to a
    substring match on prose."""

    def __init__(self, real: MarketIntelligenceEngine) -> None:
        self._real = real
        self.last_snapshot = None

    def evaluate(self, *args, **kwargs):
        self.last_snapshot = self._real.evaluate(*args, **kwargs)
        return self.last_snapshot


def _build_real_orchestrator(bridge_submit=None):
    mi_spy = _MarketIntelligenceSpy(MarketIntelligenceEngine(MarketIntelligenceConfig()))
    orchestrator = RuntimeOrchestrator(
        RuntimeConfig(),
        EvidenceEngine(EvidenceEngineConfig()),
        mi_spy,
        StrategyEngine(StrategyEngineConfig()),
        RiskEngine(RiskEngineConfig()),
        ComplianceEngine(ComplianceEngineConfig()),
        bridge_submit or make_stub_bridge_submit(),
    )
    return orchestrator, mi_spy


def _build_news_engine(primary_events=()) -> NewsIngestionEngine:
    primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [tuple(primary_events)])
    backup = FakeProvider(ProviderName.FOREX_FACTORY, [()])
    return NewsIngestionEngine(NewsIngestionConfig(), primary, backup)


class TestMarketDataIngestionFeedsRealPipelineToASubmittedTrade(unittest.TestCase):
    """The core ADR-033 SS7 proof: bars that went through validation,
    ordering, and the retention buffer -- not directly-constructed
    `Bar`s -- still drive the real Evidence -> Strategy -> Risk ->
    Compliance -> Bridge chain to a genuine trade, exactly like
    `test_integration.py::TestRealSignalEndToEnd` does with synthetic
    data built by hand."""

    def test_ingested_trending_bars_qualify_trend_continuation_and_submit(self):
        ingestion = MarketDataIngestionEngine(MarketDataIngestionConfig())
        _ingest_trending_bars(ingestion)
        bars = ingestion.get_bars(_SYMBOL, _TIMEFRAME)
        self.assertGreater(len(bars), 0, "ingestion produced no bars -- nothing to feed the pipeline")

        news = _build_news_engine(primary_events=())
        events, trusted = news.fetch_events(T0)
        self.assertTrue(trusted)
        self.assertEqual(events, ())

        ingestion.ingest_tick(TickEvent(symbol=_SYMBOL, timestamp=T0, bid=bars[-1].close - 0.0001, ask=bars[-1].close + 0.0001), now=T0)
        spread = ingestion.latest_spread(_SYMBOL)
        self.assertIsNotNone(spread)
        current_spread, average_spread = spread

        bridge_submit = make_stub_bridge_submit()
        orchestrator, mi_spy = _build_real_orchestrator(bridge_submit)
        record = orchestrator.run_cycle_for_pair(
            _SYMBOL, bars, events, current_spread, average_spread, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-3C-1",
        )

        self.assertEqual(record.outcome, CycleOutcome.SUBMITTED)
        self.assertEqual(record.selected_strategy, StrategyId.TREND_CONTINUATION)
        self.assertEqual(record.trade_intent, TradeIntent.BUY)
        self.assertFalse(mi_spy.last_snapshot.pair_safety.news.blackout_active)
        self.assertEqual(len(bridge_submit.calls), 1)


class TestNewsIngestionFeedsRealMarketIntelligenceThroughRuntime(unittest.TestCase):
    """Proves the news_ingestion -> adapter -> MarketIntelligenceEngine
    seam holds inside a real Runtime cycle, not just in
    `tests/titan_protocol/news_ingestion/test_mi_integration.py`'s direct
    `MarketIntelligenceEngine.evaluate()` calls."""

    def test_ingested_high_impact_news_reaches_mi_blackout_inside_a_real_cycle(self):
        ingestion = MarketDataIngestionEngine(MarketDataIngestionConfig())
        _ingest_trending_bars(ingestion)
        bars = ingestion.get_bars(_SYMBOL, _TIMEFRAME)

        high_impact_event = make_normalized_event(currency="USD", impact="high", scheduled_time=T0 + timedelta(minutes=10))
        news = _build_news_engine(primary_events=(high_impact_event,))
        events, trusted = news.fetch_events(T0)
        self.assertTrue(trusted)
        self.assertEqual(len(events), 1)

        orchestrator, mi_spy = _build_real_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            _SYMBOL, bars, events, 0.0002, 0.0002, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-3C-2",
        )

        self.assertTrue(mi_spy.last_snapshot.pair_safety.news.blackout_active)

    def test_both_news_providers_down_yields_untrusted_feed_caller_must_gate(self):
        """ADR-033 SS4.2: Runtime is frozen and has no `news_feed_trusted`
        passthrough -- the deployment loop, not Runtime, must treat
        `trusted=False` as "skip this cycle". This test documents that
        contract at the exact point it is produced, so a future change
        to either side cannot silently drift apart from it."""
        from titan_protocol.news_ingestion.models import ProviderUnavailable

        primary = FakeProvider(ProviderName.TRADING_ECONOMICS, [ProviderUnavailable("down")])
        backup = FakeProvider(ProviderName.FOREX_FACTORY, [ProviderUnavailable("down")])
        news = NewsIngestionEngine(NewsIngestionConfig(), primary, backup)
        events, trusted = news.fetch_events(T0)
        self.assertEqual(events, ())
        self.assertFalse(trusted)


class TestMarketDataIngestionBackfillFeedsRealPipeline(unittest.TestCase):
    """The startup path (`backfill()`) is a distinct code path from the
    live `ingest_bar()` loop above -- both must produce output the real
    pipeline accepts without error."""

    def test_backfilled_bars_drive_the_real_pipeline_without_error(self):
        ingestion = MarketDataIngestionEngine(MarketDataIngestionConfig())
        prices = _trending_prices()
        n = len(prices)
        raws = []
        for i, p in enumerate(prices):
            bar_open_time = T0 - timedelta(hours=n - i)
            raws.append(RawBar(
                symbol=_SYMBOL, timeframe=_TIMEFRAME,
                broker_timestamp=bar_open_time, source_timestamp=bar_open_time, bar_open_time=bar_open_time,
                open=p, high=p + 0.0005, low=p - 0.0005, close=p, volume=100.0,
                is_closed=True, sequence_number=i,
            ))
        status = ingestion.backfill(_SYMBOL, _TIMEFRAME, raws, now=T0)
        self.assertTrue(status.ready)

        bars = ingestion.get_bars(_SYMBOL, _TIMEFRAME)
        news = _build_news_engine(primary_events=())
        events, _trusted = news.fetch_events(T0)

        orchestrator, _mi_spy = _build_real_orchestrator()
        record = orchestrator.run_cycle_for_pair(
            _SYMBOL, bars, events, 0.0002, 0.0002, make_market_safety_inputs(),
            PortfolioState(), None, make_account_state(), make_profile(), T0, "CYCLE-3C-3",
        )
        self.assertNotEqual(record.outcome, CycleOutcome.FAILED)


if __name__ == "__main__":
    unittest.main()
