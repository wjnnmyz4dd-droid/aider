"""Autonomous Producer Runner — contracts (Phase 7A). DEMO-ONLY, FOREX-ONLY, FTMO-ONLY.

The runner is pure orchestration: it wires already-accepted components (strategy
engine, FTMO compliance engine, filesystem bridge) into one demo-only pipeline.
It reimplements NONE of their logic — no strategy rules, no compliance rules, no
news lockouts, no risk arithmetic, no signal-id computation, no bridge validation.

Determinism: the runner takes an injected ``now`` (UTC) and injected providers;
identical inputs produce identical decisions and identifiers. No RNG. No
networking. The runner never places an order and never modifies a stop.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..bridge import serialize
from ..compliance import ComplianceConfig


class RunnerMode:
    DEMO = "DEMO"
    LIVE = "LIVE"


class CycleOutcome:
    KILL_SWITCH = "KILL_SWITCH"
    NO_NEW_BAR = "NO_NEW_BAR"
    SESSION_INELIGIBLE = "SESSION_INELIGIBLE"     # Phase 9A: pre-strategy session gate
    DATA_REJECTED = "DATA_REJECTED"
    ACCOUNT_REJECTED = "ACCOUNT_REJECTED"
    NEWS_REJECTED = "NEWS_REJECTED"
    NO_CANDIDATE = "NO_CANDIDATE"
    COMPLIANCE_REJECT = "COMPLIANCE_REJECT"
    INSTRUCTION_WRITTEN = "INSTRUCTION_WRITTEN"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    ALL = (KILL_SWITCH, NO_NEW_BAR, SESSION_INELIGIBLE, DATA_REJECTED, ACCOUNT_REJECTED,
           NEWS_REJECTED, NO_CANDIDATE, COMPLIANCE_REJECT, INSTRUCTION_WRITTEN,
           DUPLICATE_SUPPRESSED)


class RunnerReason:
    """Cycle-orchestration reason codes ONLY. Component reason codes (strategy,
    compliance) are recorded verbatim from the component — never re-declared."""

    OK = "R_OK"
    KILL_SWITCH = "R_KILL_SWITCH"
    NO_NEW_BAR = "R_NO_NEW_BAR"
    SESSION_INELIGIBLE = "R_SESSION_INELIGIBLE"
    DATA_STALE = "R_DATA_STALE"
    DATA_GAP = "R_DATA_GAP"
    DATA_FUTURE_BAR = "R_DATA_FUTURE_BAR"
    DATA_UNCLOSED_BAR = "R_DATA_UNCLOSED_BAR"
    DATA_INSUFFICIENT = "R_DATA_INSUFFICIENT"
    DATA_NOT_FOREX = "R_DATA_NOT_FOREX"
    DATA_UNAVAILABLE = "R_DATA_UNAVAILABLE"
    ACCOUNT_UNAVAILABLE = "R_ACCOUNT_UNAVAILABLE"
    ACCOUNT_STALE = "R_ACCOUNT_STALE"
    ACCOUNT_ANCHOR_UNAVAILABLE = "R_ACCOUNT_ANCHOR_UNAVAILABLE"   # P3A-1 mid-day cold start
    NO_CANDIDATE = "R_NO_CANDIDATE"
    COMPLIANCE_REJECT = "R_COMPLIANCE_REJECT"
    INSTRUCTION_WRITTEN = "R_INSTRUCTION_WRITTEN"
    DUPLICATE_SUPPRESSED = "R_DUPLICATE_SUPPRESSED"
    RECONCILE_REQUIRED = "R_RECONCILE_REQUIRED"

    REQUIRED = frozenset({
        OK, KILL_SWITCH, NO_NEW_BAR, SESSION_INELIGIBLE, DATA_STALE, DATA_GAP, DATA_FUTURE_BAR,
        DATA_UNCLOSED_BAR, DATA_INSUFFICIENT, DATA_NOT_FOREX, DATA_UNAVAILABLE,
        ACCOUNT_UNAVAILABLE, ACCOUNT_STALE, ACCOUNT_ANCHOR_UNAVAILABLE, NO_CANDIDATE,
        COMPLIANCE_REJECT, INSTRUCTION_WRITTEN, DUPLICATE_SUPPRESSED, RECONCILE_REQUIRED,
    })


class RunnerRefused(RuntimeError):
    """Raised by preflight when demo-safety / FTMO-verification gates are not met.
    No override flag can bypass this."""


class InterfaceGap(RuntimeError):
    """Raised instead of creating a parallel implementation when an accepted
    component's interface cannot support the runner cleanly."""


@dataclass(frozen=True)
class RunnerConfig:
    symbols: tuple
    mode: str = RunnerMode.DEMO
    ftmo_profile_verified: bool = False
    exec_timeframe: str = "M15"
    required_timeframes: tuple = ("M15", "H1", "H4", "D1")
    cadence_sec: int = 900                      # M15
    max_data_age_sec: int = 120
    max_account_age_sec: int = 60
    max_news_age_sec: int = 3600
    continuity_bars: int = 8                    # recent exec bars checked for gaps
    compliance: ComplianceConfig = field(default_factory=ComplianceConfig)
    strategy_config: dict = field(default_factory=dict)
    # Phase 9A: canonical session gating (pre-strategy). None -> no session gate
    # (backward compatible with pre-9A runners/tests).
    session_model: object = None
    strategy_capability: object = None


@dataclass(frozen=True)
class CycleResult:
    cycle_id: str
    symbol: str
    bar_ts: str
    outcome: str
    reason_codes: tuple
    signal_id: str = None
    compliance_decision_id: str = None
    detail: dict = field(default_factory=dict)

    @property
    def wrote_bridge(self):
        return self.outcome == CycleOutcome.INSTRUCTION_WRITTEN


_TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def tf_minutes(tf):
    return _TF_MINUTES.get(tf)


def cycle_id(symbol, bar_ts, now_iso, data_versions):
    """Content-addressed 16-hex cycle id (deterministic for identical inputs)."""
    payload = serialize.canonical_json(
        {"symbol": symbol, "bar_ts": bar_ts, "now": now_iso, "data": data_versions})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
