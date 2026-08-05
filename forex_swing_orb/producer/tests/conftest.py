"""Deterministic fixtures for the Producer Runner tests (Phase 7A). No networking;
all timestamps derive from a fixed injected ``now``."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]   # .../aider
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.bridge.paths import BridgePaths                       # noqa: E402
from forex_swing_orb.compliance import ComplianceConfig, FtmoProfile        # noqa: E402


def _verified_config():
    return ComplianceConfig(profile=FtmoProfile(
        initial_balance=100000.0, account_currency="USD",
        rule_source="ftmo.com/en/trading-objectives (2-Step)",
        rule_source_verified_at="2026-08-05", profile_verified=True))
from forex_swing_orb.producer import ProducerRunner, RunnerConfig, RunnerMode  # noqa: E402
from forex_swing_orb.producer.mock_providers import (                      # noqa: E402
    MockAccountProvider, MockBrokerHealthProvider, MockMarketDataProvider,
    MockNewsProvider, StubEngine)

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)   # Wed, London session


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def make_runner(tmp_path):
    def _make(engine=None, symbols=("EURUSD.FX",), mode=RunnerMode.DEMO,
              ftmo_verified=True, compliance=None, market=None, account=None,
              news=None, broker=None, kill=None, now=NOW):
        paths = BridgePaths(tmp_path / "bridge").ensure()
        cfg = RunnerConfig(symbols=symbols, mode=mode,
                           ftmo_profile_verified=ftmo_verified,
                           compliance=compliance or _verified_config())
        market = market or MockMarketDataProvider(symbols, now)
        account = account or MockAccountProvider(now)
        news = news if news is not None else MockNewsProvider(now)
        broker = broker or MockBrokerHealthProvider()
        engine = engine or StubEngine(emit=True)
        runner = ProducerRunner(
            cfg, bridge_paths=paths, market=market, account=account, news=news,
            broker=broker, strategy=engine,
            state_path=str(tmp_path / "state.json"),
            runner_audit_path=str(tmp_path / "runner_audit.jsonl"),
            compliance_audit_path=str(tmp_path / "compliance.jsonl"),
            kill_switch=kill)
        return runner, {"paths": paths, "market": market, "account": account,
                        "news": news, "broker": broker, "engine": engine, "cfg": cfg}
    return _make
