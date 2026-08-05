"""Runtime wiring (Phase 8D) — construct real live dependencies from config.

Single source of truth for turning a validated :class:`RuntimeConfig` into the
concrete, production live components (verified FTMO profile, compliance config,
MT5-backed providers, strategy engine, broker-truth source). Both the producer and
manager ``build_from_env`` entry points delegate here so their wiring cannot drift.

DEMO-ONLY, FOREX-ONLY, FTMO 2-Step Swing only. Fails closed: an unverified /
unusable FTMO profile raises before any component is returned. No networking
beyond the injected MT5 client.
"""

from __future__ import annotations

from ..compliance import ComplianceConfig, FtmoConfig, FtmoProfile
from ..live import (BrokerHealthConfig, DailyAnchorTracker, FileNewsDataProvider,
                    Mt5AccountStateProvider, Mt5BrokerHealthProvider,
                    Mt5MarketDataProvider, SymbolMap)
from ..live import mt5_client as mc
from ..producer import RunnerConfig, RunnerMode
from ..producer.strategy_adapter import load_engine
from .config import ConfigError, password_from_env
from .slippage import BridgeSlippageSource
from .truth import Mt5TruthSource


# --------------------------------------------------------------------------- #
# Compliance / profile
# --------------------------------------------------------------------------- #
def build_profile(cfg):
    """Construct and VERIFY the FTMO 2-Step Swing profile. Fails closed."""
    profile = FtmoProfile(
        initial_balance=cfg.initial_balance,
        account_currency=cfg.account_currency,
        daily_loss_pct=cfg.daily_loss_pct,
        maximum_loss_pct=cfg.maximum_loss_pct,
        reset_timezone=cfg.reset_timezone,
        rule_source=cfg.ftmo_rule_source,
        rule_source_verified_at=cfg.ftmo_rule_source_verified_at,
        profile_verified=cfg.ftmo_profile_verified)
    err = profile.verification_error()
    if err is not None:
        raise ConfigError(f"FTMO profile not usable: {err}")
    return profile


def build_compliance_config(cfg):
    return ComplianceConfig(profile=build_profile(cfg), ftmo=FtmoConfig())


def build_runner_config(cfg, compliance=None):
    compliance = compliance or build_compliance_config(cfg)
    return RunnerConfig(
        symbols=tuple(cfg.symbols),
        mode=RunnerMode.DEMO,                 # this phase is demo-only, always
        ftmo_profile_verified=True,           # profile already verified above
        cadence_sec=cfg.cadence_sec,
        compliance=compliance,
        strategy_config={"min_history_bars": 60})


# --------------------------------------------------------------------------- #
# Live client + providers
# --------------------------------------------------------------------------- #
def build_client(cfg, env=None):   # pragma: no cover - real terminal only
    """Create the live MetaTrader5 client from config (Windows/terminal only)."""
    return mc.create_real_client(
        terminal_path=cfg.mt5_terminal_path, login=cfg.mt5_login,
        server=cfg.mt5_server, password=password_from_env(env))


def symbol_map(cfg):
    return SymbolMap(suffix=cfg.symbol_suffix)


def build_market_provider(client, cfg):
    return Mt5MarketDataProvider(client, symbol_map=symbol_map(cfg))


def build_account_provider(client, cfg):
    tracker = DailyAnchorTracker(cfg.anchor_path, reset_timezone=cfg.reset_timezone)
    return Mt5AccountStateProvider(
        client, initial_balance=cfg.initial_balance, anchor_tracker=tracker,
        symbol_map=symbol_map(cfg), daily_loss_pct=cfg.daily_loss_pct)


def build_broker_provider(client, cfg):
    slippage = BridgeSlippageSource(cfg.bridge_root)
    return Mt5BrokerHealthProvider(
        client, cfg=BrokerHealthConfig(), symbol_map=symbol_map(cfg),
        slippage_source=slippage)


def build_news_provider(cfg):
    return FileNewsDataProvider(cfg.news_file)


def build_strategy(cfg):
    return load_engine({"min_history_bars": 60})


def build_truth_source(client):
    return Mt5TruthSource(client)


def build_context_provider(client, cfg):
    """Manager market-context provider over the real MT5 market provider + the
    frozen engine's own structure extractor. Reuses the engine's DEFAULT_CONFIG
    constants (minor_pivot_k / execution_tf_minutes) — no duplicated pivot logic."""
    from ..producer.strategy_adapter import load_engine_module
    from .context import ManagerMarketContextProvider
    module = load_engine_module()
    defaults = getattr(module, "DEFAULT_CONFIG", {})
    minor_k = int(defaults.get("minor_pivot_k", 1))       # trailing structure strength
    tf_min = int(defaults.get("execution_tf_minutes", 15))
    exec_tf = {15: "M15", 60: "H1", 240: "H4", 1440: "D1"}.get(tf_min, "M15")
    return ManagerMarketContextProvider(
        build_market_provider(client, cfg), module, symbol_map=symbol_map(cfg),
        exec_timeframe=exec_tf, pivot_k=minor_k)
