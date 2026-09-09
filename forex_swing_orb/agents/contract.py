"""Versioned agent input/output contract + shared scales and reason codes.

Single source of truth for the agent-layer wire contract. Serialization and
deterministic IDs REUSE the bridge's one canonical serializer
(``forex_swing_orb.bridge.serialize``) — the agent layer never defines its own
JSON/hash logic. Everything here is advisory: nothing in this module can place a
trade, write a bridge instruction, or override a deterministic gate.
"""

from __future__ import annotations

import hashlib

from ..bridge import serialize   # the ONE canonical serializer / hasher

SCHEMA_VERSION = 1

# Agents that MAY use the shared LLM (advisory reasoning only).
LLM_ELIGIBLE_AGENTS = frozenset({
    "market_intelligence", "liquidity", "critic", "research",
    "memory_summarizer", "explainability",
})
# Agents/services that MUST remain deterministic (safety-critical).
DETERMINISTIC_ONLY = frozenset({
    "risk", "news_compliance", "decision_coordinator", "data_quality",
})


class Assessment:
    """Canonical advisory verdict scale shared by every agent (one scale)."""
    CLEAR = "CLEAR"      # no objection from this agent
    CAUTION = "CAUTION"  # proceed only with heightened scrutiny
    BLOCK = "BLOCK"      # this agent objects; advisory stop

    _SEVERITY = {CLEAR: 0, CAUTION: 1, BLOCK: 2}
    ALL = (CLEAR, CAUTION, BLOCK)

    @classmethod
    def severity(cls, value):
        return cls._SEVERITY.get(value, 2)   # unknown -> most severe (fail closed)

    @classmethod
    def worst(cls, values):
        worst = cls.CLEAR
        for v in values:
            if cls.severity(v) > cls.severity(worst):
                worst = v
        return worst


class LiquidityRating:
    """Domain-facing liquidity labels mapped onto the ONE canonical scale, so the
    coordinator still reasons in a single vocabulary (no parallel scale)."""
    FAVORABLE = "FAVORABLE"
    CAUTION = "CAUTION"
    AVOID = "AVOID"

    TO_ASSESSMENT = {
        FAVORABLE: Assessment.CLEAR,
        CAUTION: Assessment.CAUTION,
        AVOID: Assessment.BLOCK,
    }


class NewsRating:
    """Domain-facing news labels mapped onto the canonical scale."""
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"

    TO_ASSESSMENT = {
        CLEAR: Assessment.CLEAR,
        CAUTION: Assessment.CAUTION,
        BLOCK: Assessment.BLOCK,
    }


# -- confidence: one advisory scale across all agents -----------------------
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0


def confidence_band(value):
    """LOW / MEDIUM / HIGH bands over [0,1]. Advisory only."""
    if not isinstance(value, (int, float)) or value < CONFIDENCE_MIN or value > CONFIDENCE_MAX:
        return None
    if value < 0.34:
        return "LOW"
    if value < 0.67:
        return "MEDIUM"
    return "HIGH"


def valid_confidence(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and CONFIDENCE_MIN <= value <= CONFIDENCE_MAX


class ReasonCode:
    """Deterministic agent-layer reason codes."""
    OK = "A_OK"
    # data quality (fail closed)
    DQ_OK = "DQ_OK"
    DQ_MISSING_INPUT = "DQ_MISSING_INPUT"
    DQ_STALE = "DQ_STALE"
    DQ_MALFORMED = "DQ_MALFORMED"
    DQ_NON_MONOTONIC = "DQ_NON_MONOTONIC"
    DQ_NO_PROVENANCE = "DQ_NO_PROVENANCE"
    DQ_SYMBOL_MAP = "DQ_SYMBOL_MAP"
    DQ_NO_TIMEZONE = "DQ_NO_TIMEZONE"
    # contract
    E_SCHEMA = "A_E_SCHEMA"
    E_FIELDS = "A_E_FIELDS"
    E_RANGE = "A_E_RANGE"
    # agent assessments
    INSUFFICIENT_EVIDENCE = "A_INSUFFICIENT_EVIDENCE"
    NEWS_BLOCK = "NEWS_BLOCK"
    RISK_REJECT = "RISK_REJECT"
    CRITIC_BLOCK = "CRITIC_BLOCK"
    # Market Intelligence (Phase 4B, advisory interpretation of strategy facts)
    MI_TRENDING_SUPPORTIVE = "MI_TRENDING_SUPPORTIVE"
    MI_RANGING = "MI_RANGING"
    MI_TRANSITIONAL = "MI_TRANSITIONAL"
    MI_DISORDERED = "MI_DISORDERED"
    MI_STRUCTURE_CONFLICT = "MI_STRUCTURE_CONFLICT"
    MI_VOLATILITY_ABNORMAL = "MI_VOLATILITY_ABNORMAL"
    MI_SESSION_UNFAVORABLE = "MI_SESSION_UNFAVORABLE"
    MI_DATA_INSUFFICIENT = "MI_DATA_INSUFFICIENT"
    MI_UNKNOWN = "MI_UNKNOWN"
    # Liquidity (Phase 4B, closed-bar advisory inference)
    LIQUIDITY_FAVORABLE = "LIQUIDITY_FAVORABLE"
    LIQUIDITY_POOL_NEAR_TARGET = "LIQUIDITY_POOL_NEAR_TARGET"
    LIQUIDITY_POOL_BEHIND_ENTRY = "LIQUIDITY_POOL_BEHIND_ENTRY"
    LIQUIDITY_SWEEP_CONFIRMED = "LIQUIDITY_SWEEP_CONFIRMED"
    LIQUIDITY_SWEEP_UNCONFIRMED = "LIQUIDITY_SWEEP_UNCONFIRMED"
    LIQUIDITY_TRAP_RISK = "LIQUIDITY_TRAP_RISK"
    LIQUIDITY_FAILED_BREAKOUT = "LIQUIDITY_FAILED_BREAKOUT"
    LIQUIDITY_RETEST_WEAK = "LIQUIDITY_RETEST_WEAK"
    LIQUIDITY_DATA_INSUFFICIENT = "LIQUIDITY_DATA_INSUFFICIENT"
    LIQUIDITY_DATA_STALE = "LIQUIDITY_DATA_STALE"
    # News & Compliance (Phase 4B, deterministic lockout)
    NEWS_CLEAR = "NEWS_CLEAR"
    NEWS_CAUTION_WINDOW = "NEWS_CAUTION_WINDOW"
    NEWS_HIGH_IMPACT_BLOCK = "NEWS_HIGH_IMPACT_BLOCK"
    NEWS_DATA_UNAVAILABLE = "NEWS_DATA_UNAVAILABLE"
    NEWS_DATA_STALE = "NEWS_DATA_STALE"
    NEWS_DATA_MALFORMED = "NEWS_DATA_MALFORMED"
    NEWS_SOURCE_UNVERIFIED = "NEWS_SOURCE_UNVERIFIED"
    NEWS_TIMEZONE_AMBIGUOUS = "NEWS_TIMEZONE_AMBIGUOUS"
    NEWS_CURRENCY_NOT_MAPPED = "NEWS_CURRENCY_NOT_MAPPED"
    NEWS_CONFLICTING_RECORDS = "NEWS_CONFLICTING_RECORDS"
    # coordinator
    COORD_NO_TRADE_STRATEGY = "COORD_NO_TRADE_STRATEGY"
    COORD_BLOCK_NEWS = "COORD_BLOCK_NEWS"
    COORD_BLOCK_RISK = "COORD_BLOCK_RISK"
    COORD_BLOCK_DATA_QUALITY = "COORD_BLOCK_DATA_QUALITY"
    COORD_BLOCK_AGENT = "COORD_BLOCK_AGENT"
    COORD_CAUTION = "COORD_CAUTION"
    COORD_PROCEED_ADVISORY = "COORD_PROCEED_ADVISORY"


# Coordinator advisory decisions — NONE of these place or modify a trade.
class Advisory:
    PROCEED = "ADVISE_PROCEED"     # advisory only; deterministic gates still apply
    CAUTION = "ADVISE_CAUTION"
    NO_TRADE = "ADVISE_NO_TRADE"   # includes strategy no-trade / block / reject


# Strategy candidate states the coordinator is TOLD (it never computes these).
class StrategyCandidate:
    QUALIFIED = "QUALIFIED"        # deterministic strategy produced a setup
    NO_TRADE = "NO_TRADE"          # deterministic strategy produced nothing


REQUIRED_REQUEST_FIELDS = (
    "schema_version", "request_id", "symbol", "evaluation_timestamp",
    "strategy_id", "strategy_version", "market_data_reference",
    "news_data_reference", "memory_context_reference", "correlation_id",
)

REQUIRED_RESULT_FIELDS = (
    "schema_version", "agent_id", "agent_version", "request_id", "correlation_id",
    "assessment", "confidence", "evidence", "reason_codes", "data_freshness",
    "missing_inputs", "generated_timestamp",
)


def deterministic_id(*parts):
    """Content-addressed 16-hex id from the canonical serialization of parts."""
    payload = serialize.canonical_json(list(parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_request(symbol, evaluation_timestamp, strategy_id, strategy_version,
                  market_data_reference, news_data_reference,
                  memory_context_reference, correlation_id, request_id=None):
    req = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "symbol": symbol,
        "evaluation_timestamp": evaluation_timestamp,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "market_data_reference": market_data_reference,
        "news_data_reference": news_data_reference,
        "memory_context_reference": memory_context_reference,
        "correlation_id": correlation_id,
    }
    if req["request_id"] is None:
        req["request_id"] = deterministic_id(symbol, evaluation_timestamp,
                                             strategy_version, correlation_id)
    return req


def validate_request(record, now=None):
    """Structural validation of an agent request. Returns (ok, reason, detail)."""
    if not isinstance(record, dict):
        return False, ReasonCode.E_FIELDS, {"type": "not-a-dict"}
    if record.get("schema_version") != SCHEMA_VERSION:
        return False, ReasonCode.E_SCHEMA, {"schema_version": record.get("schema_version")}
    for field in REQUIRED_REQUEST_FIELDS:
        if field not in record or record[field] is None:
            return False, ReasonCode.E_FIELDS, {"missing": field}
    return True, ReasonCode.OK, {}


def build_result(agent_id, agent_version, request, assessment, confidence,
                 evidence=None, reason_codes=None, data_freshness=None,
                 missing_inputs=None, model_id=None, prompt_version=None,
                 generated_timestamp=None, extra=None):
    """Construct a versioned structured agent result (advisory only)."""
    result = {
        "schema_version": SCHEMA_VERSION,
        "agent_id": agent_id,
        "agent_version": agent_version,
        "request_id": request.get("request_id"),
        "correlation_id": request.get("correlation_id"),
        "symbol": request.get("symbol"),
        "assessment": assessment,
        "confidence": confidence,
        "evidence": evidence or {},
        "reason_codes": list(reason_codes or []),
        "data_freshness": data_freshness or {},
        "missing_inputs": list(missing_inputs or []),
        "model_id": model_id,             # set iff an LLM was used
        "prompt_version": prompt_version, # set iff an LLM was used
        "generated_timestamp": generated_timestamp,
    }
    if extra:
        result["evidence"].update(extra)
    return result


def validate_result(record):
    """Structural validation of an agent result. Returns (ok, reason, detail)."""
    if not isinstance(record, dict):
        return False, ReasonCode.E_FIELDS, {"type": "not-a-dict"}
    if record.get("schema_version") != SCHEMA_VERSION:
        return False, ReasonCode.E_SCHEMA, {"schema_version": record.get("schema_version")}
    for field in REQUIRED_RESULT_FIELDS:
        if field not in record:
            return False, ReasonCode.E_FIELDS, {"missing": field}
    if record["assessment"] not in Assessment.ALL:
        return False, ReasonCode.E_FIELDS, {"assessment": record["assessment"]}
    if not valid_confidence(record["confidence"]):
        return False, ReasonCode.E_RANGE, {"confidence": record["confidence"]}
    # if an LLM was used both model_id and prompt_version must be captured
    if (record.get("model_id") is None) != (record.get("prompt_version") is None):
        return False, ReasonCode.E_FIELDS, {"llm_capture": "model_id/prompt_version"}
    return True, ReasonCode.OK, {}


def serialize_result(record):
    """Canonical, byte-stable serialization (reuses the bridge serializer)."""
    return serialize.canonical_json(record)
