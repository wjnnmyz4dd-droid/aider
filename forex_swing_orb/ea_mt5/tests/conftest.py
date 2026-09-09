"""Fixtures for the MT5 execution-adapter tests. Deterministic; no networking."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]   # .../aider
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # for ea_helpers

from forex_swing_orb import bridge as bridge_pkg                      # noqa: E402
from forex_swing_orb.bridge.audit import AuditLog                     # noqa: E402
from forex_swing_orb.bridge.config import DEFAULT_CONFIG              # noqa: E402
from forex_swing_orb.bridge.ledger import DedupLedger                 # noqa: E402
from forex_swing_orb.bridge.paths import BridgePaths                  # noqa: E402
from forex_swing_orb.ea_mt5 import mock_mt5                           # noqa: E402
from forex_swing_orb.ea_mt5.execution_consumer import ExecutionConsumer  # noqa: E402

from ea_helpers import NOW                                            # noqa: E402


@pytest.fixture
def bridge():
    return bridge_pkg


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def mt5():
    m = mock_mt5.MockMT5()
    m.add_symbol("EURUSD")     # canonical EURUSD.FX -> broker EURUSD (suffix "")
    m.add_symbol("GBPUSD")
    return m


@pytest.fixture
def env(tmp_path, mt5):
    """A wired execution adapter over a fresh bridge tree and mock terminal."""
    paths = BridgePaths(tmp_path).ensure()
    ledger = DedupLedger(paths.dedup_ledger)
    audit = AuditLog(paths.audit_log)
    ec = ExecutionConsumer(paths, DEFAULT_CONFIG, ledger, audit, mt5)
    return ec
