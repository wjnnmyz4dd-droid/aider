"""Deterministic transport validation pipeline (spec §7 subset / §2.1).

Ordered checks; STOP on first failure and return its reason code. Everything
fails closed. Steps 9-15 of §7 (market/account freshness, news re-validation,
Titan compliance, exposure/spread/kill-switch, execution) are DOWNSTREAM and are
not performed here.
"""

from __future__ import annotations

import math

from . import serialize
from .contract import REQUIRED_INSTRUCTION_FIELDS, SESSION_ID_RE, DIRECTIONS, ReasonCode
from .paths import SIGNAL_ID_RE
import re


def _finite_positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and math.isfinite(x) and x > 0


def validate_record(record, cfg, now, expected_signal_id=None):
    """Structural/content validation (spec §7 transport subset, minus dedup).

    Dedup is handled once by the shared SeenResolver in the consumer, not here,
    so there is a single dedup path. ``now`` is a tz-aware UTC datetime.
    Returns (ok, reason_code, detail)."""
    # 2. supported schema version
    if record.get("schema_version") not in cfg.schema_version_allowlist:
        return False, ReasonCode.E_SCHEMA, {"schema_version": record.get("schema_version")}
    # 3. integrity / checksum
    if not serialize.verify_integrity_digest(record):
        return False, ReasonCode.E_INTEGRITY, {}
    # 4. required fields present & typed
    for field in REQUIRED_INSTRUCTION_FIELDS:
        if field not in record or record[field] is None:
            return False, ReasonCode.E_FIELDS, {"missing": field}
    if not isinstance(record["evidence_summary"], dict) or not isinstance(record["news_eligibility"], dict):
        return False, ReasonCode.E_FIELDS, {"bad_type": "evidence_summary/news_eligibility"}
    # 4b. known producer
    if record["strategy_id"] not in cfg.strategy_id_allowlist:
        return False, ReasonCode.E_STRATEGY, {"strategy_id": record["strategy_id"]}
    if record["strategy_version"] not in cfg.strategy_version_allowlist:
        return False, ReasonCode.E_STRATEGY, {"strategy_version": record["strategy_version"]}
    # signal_id well-formed and consistent with the filename
    signal_id = record["signal_id"]
    if not (isinstance(signal_id, str) and SIGNAL_ID_RE.match(signal_id)):
        return False, ReasonCode.E_ID, {"signal_id": signal_id}
    if expected_signal_id is not None and signal_id != expected_signal_id:
        return False, ReasonCode.E_ID, {"signal_id": signal_id, "filename": expected_signal_id}
    # session_id well-formed (transport shape only; enablement is producer authority)
    if not (isinstance(record["session_id"], str) and re.match(SESSION_ID_RE, record["session_id"])):
        return False, ReasonCode.E_FIELDS, {"session_id": record["session_id"]}
    # (dedup is resolved once by the shared SeenResolver in the consumer)
    # 6. expiry (expired iff now >= expiration_timestamp — strategy spec §8.2)
    exp = serialize.parse_iso(record["expiration_timestamp"])
    gen = serialize.parse_iso(record["generated_timestamp"])
    if exp is None or gen is None:
        return False, ReasonCode.E_FIELDS, {"bad_timestamp": True}
    if now >= exp:
        return False, ReasonCode.E_EXPIRED, {"expiration": record["expiration_timestamp"]}
    # 6b. implausible future generated_timestamp (clock-skew guard)
    if (gen - now).total_seconds() > cfg.future_skew_tolerance_sec:
        return False, ReasonCode.E_FUTURE, {"generated": record["generated_timestamp"]}
    # 7. symbol format (canonical [A-Z]{6}.FX; NO broker mapping here)
    if not re.match(cfg.symbol_pattern, str(record["symbol"])):
        return False, ReasonCode.E_SYMBOL, {"symbol": record["symbol"]}
    # 8. structural direction & prices
    direction = record["direction"]
    if direction not in DIRECTIONS:
        return False, ReasonCode.E_STRUCT, {"direction": direction}
    entry, stop, tp = record["entry_price"], record["stop_loss"], record["take_profit"]
    if not (_finite_positive(entry) and _finite_positive(stop) and _finite_positive(tp)):
        return False, ReasonCode.E_STRUCT, {"prices": [entry, stop, tp]}
    rf = record["risk_fraction"]
    if not (isinstance(rf, (int, float)) and not isinstance(rf, bool) and 0 < rf <= 1):
        return False, ReasonCode.E_STRUCT, {"risk_fraction": rf}
    if direction == "LONG" and not (stop < entry < tp):
        return False, ReasonCode.E_STRUCT, {"geometry": "long"}
    if direction == "SHORT" and not (stop > entry > tp):
        return False, ReasonCode.E_STRUCT, {"geometry": "short"}
    return True, ReasonCode.OK, {"signal_id": signal_id}
