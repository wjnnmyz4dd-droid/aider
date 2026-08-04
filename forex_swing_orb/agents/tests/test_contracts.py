"""Contract tests: schema version, missing inputs, confidence range, reason
codes, serialization, LLM-provenance capture. (Test reqs 1-7, 22.)"""

from __future__ import annotations

import json

import pytest

from forex_swing_orb.agents import (Assessment, SCHEMA_VERSION, build_request,
                                    build_result, validate_request, validate_result,
                                    confidence_band)
from forex_swing_orb.agents.contract import ReasonCode, serialize_result
from conftest import make_request


def test_valid_request_passes():
    ok, reason, _ = validate_request(make_request())
    assert ok and reason == ReasonCode.OK


def test_schema_version_rejection_request():
    req = make_request()
    req["schema_version"] = 999
    ok, reason, _ = validate_request(req)
    assert not ok and reason == ReasonCode.E_SCHEMA


def test_missing_input_fails_closed_request():
    req = make_request()
    del req["symbol"]
    ok, reason, detail = validate_request(req)
    assert not ok and reason == ReasonCode.E_FIELDS and detail["missing"] == "symbol"


def _result(**kw):
    base = dict(agent_id="market_intelligence", agent_version="0.1.0",
                request=make_request(), assessment=Assessment.CLEAR, confidence=0.8,
                reason_codes=[ReasonCode.OK], generated_timestamp="2024-01-25T12:00:00Z")
    base.update(kw)
    return build_result(**base)


def test_result_schema_version_present():
    assert _result()["schema_version"] == SCHEMA_VERSION
    ok, _, _ = validate_result(_result())
    assert ok


def test_confidence_range_enforced():
    ok, reason, _ = validate_result(_result(confidence=1.5))
    assert not ok and reason == ReasonCode.E_RANGE
    ok, reason, _ = validate_result(_result(confidence=-0.1))
    assert not ok and reason == ReasonCode.E_RANGE


def test_confidence_scale_bands():
    assert confidence_band(0.1) == "LOW"
    assert confidence_band(0.5) == "MEDIUM"
    assert confidence_band(0.9) == "HIGH"
    assert confidence_band(1.1) is None


def test_assessment_must_be_canonical():
    ok, reason, _ = validate_result(_result(assessment="MAYBE"))
    assert not ok and reason == ReasonCode.E_FIELDS


def test_llm_provenance_paired():
    # model_id without prompt_version is invalid (and vice versa)
    ok, reason, _ = validate_result(_result(model_id="m", prompt_version=None))
    assert not ok
    ok, _, _ = validate_result(_result(model_id="m", prompt_version="p.v1"))
    assert ok


def test_result_serialization_is_canonical_json():
    text = serialize_result(_result())
    parsed = json.loads(text)
    assert parsed["agent_id"] == "market_intelligence"
    # canonical: sorted keys, compact separators
    assert text == json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def test_deterministic_reason_codes_are_stable():
    r1 = _result()
    r2 = _result()
    assert r1["reason_codes"] == r2["reason_codes"] == [ReasonCode.OK]
