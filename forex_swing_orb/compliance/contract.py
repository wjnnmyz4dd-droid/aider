"""Deterministic FTMO Compliance Engine — frozen contracts (Phase 5C).

The compliance engine is a MANDATORY, deterministic gate that sits between the
authoritative Session Edge strategy and the Filesystem Bridge. No trade may reach
the bridge without a ``COMPLIANCE_PASS``.

Invariants (frozen in Phase 5C design):
  * Pure/deterministic: identical inputs -> identical decision and decision_id.
  * No wall clock (``now`` is injected), no RNG, no networking, no LLM authority.
  * Fail closed: any missing / malformed / stale / ambiguous input -> REJECT.
  * Forex-only, FTMO-only.
  * Reuses ``bridge.serialize`` for canonical JSON + content-addressed ids; it
    never re-implements serialization or hashing.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field

from ..bridge import serialize

SCHEMA_VERSION = 1
ENGINE_VERSION = "compliance.ftmo.v1.0.0"


class Decision:
    PASS = "PASS"
    REJECT = "REJECT"
    ALL = (PASS, REJECT)


class Stage:
    """Frozen evaluation stages, in mandatory execution order (Phase 5C)."""

    KILL_SWITCH = "kill_switch"
    MARKET = "market"
    FTMO = "ftmo"
    SESSION = "session"
    NEWS = "news"
    BROKER_HEALTH = "broker_health"
    RISK = "risk"
    ORDER = (KILL_SWITCH, MARKET, FTMO, SESSION, NEWS, BROKER_HEALTH, RISK)


class ReasonCode:
    """Complete deterministic registry. No generic failures: every rejection maps
    to exactly one primary code (plus optional supporting codes)."""

    # -- pass -----------------------------------------------------------------
    COMPLIANCE_PASS = "COMPLIANCE_PASS"
    # -- guard ----------------------------------------------------------------
    KILL_SWITCH = "KILL_SWITCH"
    # -- market / candidate ---------------------------------------------------
    UNKNOWN_STATE = "UNKNOWN_STATE"
    CANDIDATE_MALFORMED = "CANDIDATE_MALFORMED"
    SYMBOL_NOT_FOREX = "SYMBOL_NOT_FOREX"
    MTF_CONFLICT = "MTF_CONFLICT"
    MARKET_CLOSED = "MARKET_CLOSED"
    # -- ftmo -----------------------------------------------------------------
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_ACCOUNT_LOSS = "MAX_ACCOUNT_LOSS"
    MAX_POSITIONS = "MAX_POSITIONS"
    ONE_PER_SYMBOL = "ONE_PER_SYMBOL"
    WEEKEND_BLOCK = "WEEKEND_BLOCK"
    INTERNAL_BUFFER_TRIP = "INTERNAL_BUFFER_TRIP"
    # -- session --------------------------------------------------------------
    SESSION_BLOCK = "SESSION_BLOCK"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    # -- news -----------------------------------------------------------------
    NEWS_LOCKOUT = "NEWS_LOCKOUT"
    PAIR_BLOCKED = "PAIR_BLOCKED"
    NEWS_DATA_UNAVAILABLE = "NEWS_DATA_UNAVAILABLE"
    NEWS_DATA_STALE = "NEWS_DATA_STALE"
    NEWS_SOURCE_UNVERIFIED = "NEWS_SOURCE_UNVERIFIED"
    NEWS_CONFLICTING_RECORDS = "NEWS_CONFLICTING_RECORDS"
    # -- broker health --------------------------------------------------------
    BROKER_UNHEALTHY = "BROKER_UNHEALTHY"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    TERMINAL_DISCONNECTED = "TERMINAL_DISCONNECTED"
    BRIDGE_UNHEALTHY = "BRIDGE_UNHEALTHY"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    ACK_MISSING = "ACK_MISSING"
    # -- risk -----------------------------------------------------------------
    RISK_PER_TRADE_EXCEEDED = "RISK_PER_TRADE_EXCEEDED"
    RISK_PROJECTED_BREACH = "RISK_PROJECTED_BREACH"

    REQUIRED = frozenset({
        COMPLIANCE_PASS, KILL_SWITCH, UNKNOWN_STATE, CANDIDATE_MALFORMED,
        SYMBOL_NOT_FOREX, MTF_CONFLICT, MARKET_CLOSED, DAILY_LOSS_LIMIT,
        MAX_ACCOUNT_LOSS, MAX_POSITIONS, ONE_PER_SYMBOL, WEEKEND_BLOCK,
        INTERNAL_BUFFER_TRIP, SESSION_BLOCK, OUTSIDE_SESSION, NEWS_LOCKOUT,
        PAIR_BLOCKED, NEWS_DATA_UNAVAILABLE, NEWS_DATA_STALE,
        NEWS_SOURCE_UNVERIFIED, NEWS_CONFLICTING_RECORDS, BROKER_UNHEALTHY,
        SPREAD_TOO_HIGH, SLIPPAGE_TOO_HIGH, TERMINAL_DISCONNECTED,
        BRIDGE_UNHEALTHY, MARKET_DATA_STALE, ACK_MISSING,
        RISK_PER_TRADE_EXCEEDED, RISK_PROJECTED_BREACH,
    })


def validate_reason(code):
    """True iff ``code`` is a registered deterministic reason code."""
    return code in ReasonCode.REQUIRED


# ---------------------------------------------------------------------------
# Frozen configuration (operator-set; stable across a trading day).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FtmoConfig:
    daily_loss_pct: float = 0.05            # FTMO daily hard limit (of daily anchor equity)
    max_account_loss_pct: float = 0.10      # FTMO overall hard limit (of initial balance)
    safety_buffer_fraction: float = 0.20    # internal cushion; internal = hard*(1-f)
    max_open_positions: int = 5
    max_risk_per_trade_pct: float = 0.01
    one_position_per_symbol: bool = True
    weekend_flat_required: bool = True


@dataclass(frozen=True)
class NewsLockoutConfig:
    pre_lockout_min: int = 15               # default window: 15 before ...
    post_lockout_min: int = 15              # ... through event ... 15 after
    max_age_sec: int = 3600
    require_verified: bool = True


@dataclass(frozen=True)
class SessionConfig:
    # session windows are UTC minutes-of-day; wrap (open>close) is honored.
    sessions: tuple = (
        ("SYDNEY", 1260, 360),
        ("TOKYO", 0, 540),
        ("LONDON", 420, 960),
        ("NEWYORK", 720, 1260),
    )
    allowed_sessions: tuple = ("SYDNEY", "TOKYO", "LONDON", "NEWYORK")
    friday_close_min: int = None            # e.g. 1200 => flat from 20:00 UTC Fri
    sunday_open_min: int = None             # e.g. 1320 => no entries before 22:00 UTC Sun
    weekend_isoweekdays: tuple = (6, 7)     # Sat, Sun (FTMO weekend-flat for entries)


@dataclass(frozen=True)
class ComplianceConfig:
    ftmo: FtmoConfig = field(default_factory=FtmoConfig)
    news: NewsLockoutConfig = field(default_factory=NewsLockoutConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

    def digest(self):
        """Stable 16-hex digest of the whole config, for audit reproducibility."""
        payload = serialize.canonical_json({
            "ftmo": asdict(self.ftmo),
            "news": asdict(self.news),
            "session": asdict(self.session),
        })
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Gate verdict + engine decision.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GateVerdict:
    stage: str
    passed: bool
    reason_codes: tuple
    evidence: dict

    def to_dict(self):
        return {
            "stage": self.stage,
            "passed": self.passed,
            "reason_codes": list(self.reason_codes),
            "evidence": _sanitize(self.evidence),
        }


@dataclass(frozen=True)
class ComplianceDecision:
    decision: str
    primary_reason_code: str
    reason_codes: tuple
    gate_verdicts: tuple            # of GateVerdict, in execution order
    audit_record: dict             # canonical, includes decision_id

    @property
    def is_pass(self):
        return self.decision == Decision.PASS

    @property
    def decision_id(self):
        return self.audit_record.get("decision_id")


# ---------------------------------------------------------------------------
# Helpers shared by gates / engine / dashboard (single source of truth).
# ---------------------------------------------------------------------------
def finite(value):
    """Return ``value`` as float iff it is a finite real number, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _sanitize(obj):
    """Recursively coerce a value into JSON-/canonical-safe form (no NaN/inf)."""
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def ftmo_limits(account_state, cfg):
    """Deterministic FTMO + internal thresholds. Internal < FTMO always."""
    anchor = finite(account_state.get("daily_anchor_equity"))
    initial = finite(account_state.get("initial_balance"))
    if anchor is None or initial is None or anchor <= 0 or initial <= 0:
        return None
    ftmo_daily = anchor * cfg.daily_loss_pct
    ftmo_max = initial * cfg.max_account_loss_pct
    keep = 1.0 - cfg.safety_buffer_fraction
    return {
        "ftmo_daily_limit": ftmo_daily,
        "internal_daily_limit": ftmo_daily * keep,
        "ftmo_max_loss": ftmo_max,
        "internal_max_loss": ftmo_max * keep,
    }


def candidate_risk_amount(candidate, account_state):
    """Declared risk in account currency = daily anchor equity * risk_fraction.
    (The EA never sizes from risk_fraction; compliance validates the DECLARED
    risk against caps/buffers only.) None on any invalid input."""
    rf = finite(candidate.get("risk_fraction"))
    anchor = finite(account_state.get("daily_anchor_equity"))
    if rf is None or anchor is None or rf < 0 or anchor <= 0:
        return None
    return anchor * rf


def decision_id(body):
    """Content-addressed 16-hex id over the canonical body WITHOUT its own id."""
    without = {k: v for k, v in body.items() if k != "decision_id"}
    payload = serialize.canonical_json(_sanitize(without))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
