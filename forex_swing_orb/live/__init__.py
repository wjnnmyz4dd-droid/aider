"""Session Edge live MT5-backed provider layer (Phase 8A) — DEMO-ONLY, FOREX-ONLY.

Read-only adapters that normalize live MetaTrader 5 data into the accepted
provider contracts for the Producer Runner, Manager Service, and Compliance
Engine. No trading logic, no networking beyond the injected MT5 client, no
scraping. The concrete providers run only on a Windows host with MetaTrader5;
off-host they are exercised via the injected FakeMt5Client.
"""

from __future__ import annotations

from .mt5_client import FakeMt5Client, create_real_client
from .providers import (BrokerHealthConfig, DailyAnchorTracker, FileNewsDataProvider,
                        Mt5AccountStateProvider, Mt5BrokerHealthProvider,
                        Mt5MarketDataProvider, SymbolMap)

__all__ = [
    "FakeMt5Client", "create_real_client", "SymbolMap", "DailyAnchorTracker",
    "Mt5MarketDataProvider", "Mt5AccountStateProvider", "Mt5BrokerHealthProvider",
    "BrokerHealthConfig", "FileNewsDataProvider",
]
