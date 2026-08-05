"""Deterministic fixtures for the manage-channel tests (Phase 7B-B). No networking;
fixed injected clock; shared mock terminal between adapter (truth) and consumer (apply)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forex_swing_orb.ea_mt5 import mock_mt5                                 # noqa: E402
from forex_swing_orb.ea_mt5.position_manager import PositionManager        # noqa: E402
from forex_swing_orb.manage import (BridgeMt5Adapter, ManageConsumer,      # noqa: E402
                                    ManagePaths, ManagerService)

NOW = datetime(2026, 1, 7, 10, 0, 0, tzinfo=timezone.utc)
BUY = mock_mt5.ORDER_TYPE_BUY


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def wired(tmp_path):
    """A fully wired manage channel over one shared mock terminal."""
    mt5 = mock_mt5.MockMT5()
    mt5.add_symbol("EURUSD")
    mpaths = ManagePaths(tmp_path / "bridge").ensure()
    consumer = ManageConsumer(mt5, mpaths)
    adapter = BridgeMt5Adapter(
        mt5, mpaths, now_fn=lambda: NOW, timeout_sec=5, poll_interval_sec=1,
        sleep_fn=lambda s: None, pump=lambda now: consumer.run_once(now))
    pm = PositionManager(adapter, str(tmp_path / "pm_audit.jsonl"))
    manager = ManagerService(pm, adapter, mpaths, now_fn=lambda: NOW,
                             health_path=str(tmp_path / "manager_health.json"))
    return {"mt5": mt5, "mpaths": mpaths, "consumer": consumer, "adapter": adapter,
            "pm": pm, "manager": manager, "tmp": tmp_path}


@pytest.fixture
def long_pos(wired):
    """Open a LONG EURUSD position (entry 1.10000, sl 1.09800 => R=20 pips)."""
    def _open(signal_id="0123456789abcdef", ticket=5000001, entry=1.10000,
              sl=1.09800, tp=1.10600):
        wired["mt5"].positions[ticket] = mock_mt5.Position(
            ticket=ticket, symbol="EURUSD", type=BUY, volume=0.10,
            price_open=entry, sl=sl, tp=tp, comment=signal_id)
        wired["pm"].register(signal_id, ticket, "EURUSD", "LONG", entry, sl, tp, NOW)
        return signal_id, ticket
    return _open
