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
    # -- ftmo profile (Phase 8C: FTMO_TWO_STEP + FTMO_SWING) ------------------
    FTMO_PROFILE_UNVERIFIED = "FTMO_PROFILE_UNVERIFIED"
    FTMO_PROGRAM_UNSUPPORTED = "FTMO_PROGRAM_UNSUPPORTED"
    FTMO_ACCOUNT_TYPE_UNSUPPORTED = "FTMO_ACCOUNT_TYPE_UNSUPPORTED"
    FTMO_INITIAL_BALANCE_INVALID = "FTMO_INITIAL_BALANCE_INVALID"
    # -- ftmo daily anchor (M2/M3: Prague day-start balance) ------------------
    FTMO_DAILY_ANCHOR_MISSING = "FTMO_DAILY_ANCHOR_MISSING"
    FTMO_DAILY_ANCHOR_STALE = "FTMO_DAILY_ANCHOR_STALE"
    FTMO_DAILY_ANCHOR_CONFLICT = "FTMO_DAILY_ANCHOR_CONFLICT"
    PRAGUE_ROLLOVER_FAILED = "PRAGUE_ROLLOVER_FAILED"
    # -- ftmo loss rules (M1: initial-capital basis, static max) --------------
    FTMO_DAILY_LOSS_BREACH = "FTMO_DAILY_LOSS_BREACH"
    PROJECTED_DAILY_LOSS_BREACH = "PROJECTED_DAILY_LOSS_BREACH"
    INTERNAL_DAILY_BUFFER_TRIP = "INTERNAL_DAILY_BUFFER_TRIP"
    FTMO_MAXIMUM_LOSS_BREACH = "FTMO_MAXIMUM_LOSS_BREACH"
    INTERNAL_MAXIMUM_LOSS_BUFFER_TRIP = "INTERNAL_MAXIMUM_LOSS_BUFFER_TRIP"
    # -- internal (Session Edge) overlays: NOT official FTMO Swing rules ------
    MAX_POSITIONS = "MAX_POSITIONS"
    ONE_PER_SYMBOL = "ONE_PER_SYMBOL"
    INTERNAL_WEEKEND_POLICY = "INTERNAL_WEEKEND_POLICY"
    # -- session --------------------------------------------------------------
    SESSION_BLOCK = "SESSION_BLOCK"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    # -- news: Session Edge INTERNAL safety overlay (NOT an FTMO Swing rule) ---
    INTERNAL_NEWS_LOCKOUT = "INTERNAL_NEWS_LOCKOUT"
    INTERNAL_NEWS_LOCKOUT_EXPIRED = "INTERNAL_NEWS_LOCKOUT_EXPIRED"
    PAIR_BLOCKED = "PAIR_BLOCKED"
    NEWS_DATA_UNAVAILABLE = "NEWS_DATA_UNAVAILABLE"
    NEWS_DATA_STALE = "NEWS_DATA_STALE"
    NEWS_SOURCE_UNVERIFIED = "NEWS_SOURCE_UNVERIFIED"
    NEWS_DATA_CONFLICT = "NEWS_DATA_CONFLICT"
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
        SYMBOL_NOT_FOREX, MTF_CONFLICT, MARKET_CLOSED,
        FTMO_PROFILE_UNVERIFIED, FTMO_PROGRAM_UNSUPPORTED,
        FTMO_ACCOUNT_TYPE_UNSUPPORTED, FTMO_INITIAL_BALANCE_INVALID,
        FTMO_DAILY_ANCHOR_MISSING, FTMO_DAILY_ANCHOR_STALE,
        FTMO_DAILY_ANCHOR_CONFLICT, PRAGUE_ROLLOVER_FAILED,
        FTMO_DAILY_LOSS_BREACH, PROJECTED_DAILY_LOSS_BREACH,
        INTERNAL_DAILY_BUFFER_TRIP, FTMO_MAXIMUM_LOSS_BREACH,
        INTERNAL_MAXIMUM_LOSS_BUFFER_TRIP, MAX_POSITIONS, ONE_PER_SYMBOL,
        INTERNAL_WEEKEND_POLICY, SESSION_BLOCK, OUTSIDE_SESSION,
        INTERNAL_NEWS_LOCKOUT, INTERNAL_NEWS_LOCKOUT_EXPIRED, PAIR_BLOCKED,
        NEWS_DATA_UNAVAILABLE, NEWS_DATA_STALE, NEWS_SOURCE_UNVERIFIED,
        NEWS_DATA_CONFLICT, BROKER_UNHEALTHY, SPREAD_TOO_HIGH, SLIPPAGE_TOO_HIGH,
        TERMINAL_DISCONNECTED, BRIDGE_UNHEALTHY, MARKET_DATA_STALE, ACK_MISSING,
        RISK_PER_TRADE_EXCEEDED, RISK_PROJECTED_BREACH,
    })


def validate_reason(code):
    """True iff ``code`` is a registered deterministic reason code."""
    return code in ReasonCode.REQUIRED


# ---------------------------------------------------------------------------
# Frozen configuration (operator-set; stable across a trading day).
# ---------------------------------------------------------------------------
class ProgramType:
    FTMO_TWO_STEP = "FTMO_TWO_STEP"
    FTMO_ONE_STEP = "FTMO_ONE_STEP"          # NOT implemented this phase (rejected)
    SUPPORTED = frozenset({FTMO_TWO_STEP})


class AccountType:
    FTMO_SWING = "FTMO_SWING"
    FTMO_NORMAL = "FTMO_NORMAL"              # NOT implemented this phase (rejected)
    SUPPORTED = frozenset({FTMO_SWING})


@dataclass(frozen=True)
class FtmoProfile:
    """The single explicit, verified FTMO profile (Phase 8C). Official rule
    percentages/timezone come from the verified source; nothing is guessed."""

    program: str = ProgramType.FTMO_TWO_STEP
    account_type: str = AccountType.FTMO_SWING
    initial_balance: float = None            # operator-verified funded balance
    account_currency: str = None
    daily_loss_pct: float = 0.05             # FTMO 2-Step: 5% of INITIAL capital
    maximum_loss_pct: float = 0.10           # FTMO 2-Step: static 10% of INITIAL capital
    reset_timezone: str = "Europe/Prague"    # daily reset 00:00 CE(S)T
    rule_source: str = None                  # e.g. "ftmo.com/en/trading-objectives (2-Step)"
    rule_source_verified_at: str = None      # ISO-8601 date of the Phase 8B verification
    profile_version: str = "ftmo.two_step.swing.v1"
    profile_verified: bool = False           # never silently True

    def verification_error(self):
        """Return a ReasonCode if the profile cannot be used, else None (fail closed)."""
        if self.program not in ProgramType.SUPPORTED:
            return ReasonCode.FTMO_PROGRAM_UNSUPPORTED
        if self.account_type not in AccountType.SUPPORTED:
            return ReasonCode.FTMO_ACCOUNT_TYPE_UNSUPPORTED
        if finite(self.initial_balance) is None or self.initial_balance <= 0:
            return ReasonCode.FTMO_INITIAL_BALANCE_INVALID
        if not (self.rule_source and self.rule_source_verified_at):
            return ReasonCode.FTMO_PROFILE_UNVERIFIED
        if not _tz_loadable(self.reset_timezone):
            return ReasonCode.PRAGUE_ROLLOVER_FAILED
        if not self.profile_verified:
            return ReasonCode.FTMO_PROFILE_UNVERIFIED
        return None


@dataclass(frozen=True)
class FtmoConfig:
    """Session Edge INTERNAL safety overlays — NOT official FTMO Swing rules."""

    safety_buffer_fraction: float = 0.20     # internal cushion; internal triggers before FTMO
    max_open_positions: int = 5              # internal risk overlay
    max_risk_per_trade_pct: float = 0.01     # internal risk overlay
    one_position_per_symbol: bool = True     # internal risk overlay
    internal_weekend_flat: bool = False      # internal-only; FTMO Swing allows weekend holding


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
    profile: FtmoProfile = field(default_factory=FtmoProfile)   # official FTMO 2-Step Swing
    ftmo: FtmoConfig = field(default_factory=FtmoConfig)         # internal overlays
    news: NewsLockoutConfig = field(default_factory=NewsLockoutConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

    def digest(self):
        """Stable 16-hex digest of the whole config, for audit reproducibility."""
        payload = serialize.canonical_json({
            "profile": asdict(self.profile),
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


def _tz_loadable(name):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
        return True
    except Exception:
        return False


def prague_trading_day(now, reset_timezone="Europe/Prague"):
    """The FTMO trading-day key: the local calendar date at ``now`` in the reset
    timezone (00:00 CE(S)T boundary). DST-aware. None if the tz cannot load or
    ``now`` is naive/invalid (fail closed)."""
    try:
        from zoneinfo import ZoneInfo
        if now is None or now.tzinfo is None:
            return None
        return now.astimezone(ZoneInfo(reset_timezone)).strftime("%Y-%m-%d")
    except Exception:
        return None


def ftmo_levels(account_state, profile, cfg):
    """FTMO 2-Step levels from the INITIAL capital, anchored to the DAY-START
    BALANCE (M1/M3). Internal thresholds are strictly safer (trigger first).
    Returns a dict, or (None, reason) semantics via caller checks.

    Official daily level  = day_start_balance − daily_loss_pct × initial_balance
    Official max level     = initial_balance   − maximum_loss_pct × initial_balance (static)
    Breach iff current equity < level (equality = safe).
    """
    day_start_balance = finite(account_state.get("day_start_balance"))
    initial = finite(profile.initial_balance)
    if initial is None or initial <= 0:
        return None
    if day_start_balance is None or day_start_balance <= 0:
        return None
    keep = 1.0 - cfg.safety_buffer_fraction
    official_daily_amount = profile.daily_loss_pct * initial
    internal_daily_amount = official_daily_amount * keep
    official_max_amount = profile.maximum_loss_pct * initial
    internal_max_amount = official_max_amount * keep
    return {
        "initial_balance": initial,
        "day_start_balance": day_start_balance,
        "official_daily_amount": official_daily_amount,
        "internal_daily_amount": internal_daily_amount,
        "official_daily_level": day_start_balance - official_daily_amount,
        "internal_daily_level": day_start_balance - internal_daily_amount,   # higher/safer
        "official_max_amount": official_max_amount,
        "internal_max_amount": internal_max_amount,
        "official_max_level": initial - official_max_amount,                  # static (no trailing)
        "internal_max_level": initial - internal_max_amount,
    }


def candidate_risk_amount(candidate, profile):
    """Declared worst-case per-trade loss = risk_fraction × INITIAL capital (fixed,
    deterministic base; does not grow with account equity). None on invalid input."""
    rf = finite(candidate.get("risk_fraction"))
    initial = finite(profile.initial_balance)
    if rf is None or initial is None or rf < 0 or initial <= 0:
        return None
    return initial * rf


def decision_id(body):
    """Content-addressed 16-hex id over the canonical body WITHOUT its own id."""
    without = {k: v for k, v in body.items() if k != "decision_id"}
    payload = serialize.canonical_json(_sanitize(without))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
