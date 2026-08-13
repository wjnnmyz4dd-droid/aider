"""PR-3I / M9 (EA half) — executed volume is the operator DefaultVolume, not risk.

The frozen v1 instruction carries ``risk_fraction`` but NO executable volume, so
the execution adapter sizes every order from ``default_volume`` (the shipped MQL5
EA uses ``DefaultVolume`` identically). The executed lot is therefore INDEPENDENT
of the authorized ``risk_fraction`` — the concrete reason compliance cannot prove
actual monetary risk (M9 blocked). No production change; these prove the gap.
"""

from __future__ import annotations

import tempfile

from forex_swing_orb.bridge.contract import ResultState, REQUIRED_INSTRUCTION_FIELDS
from forex_swing_orb.validation import harness as H


def _executed_volumes(mt5, sid):
    return sorted(p.volume for p in mt5.positions.values() if p.comment == sid)


def test_executed_volume_is_default_not_derived_from_risk_fraction():
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp(), default_volume=0.10)
    rec = H.make_instruction(); rec["risk_fraction"] = 0.0025
    H.produce(paths, rec)
    r = H.drain(ec)[0]
    assert r["status"] == ResultState.EXECUTED
    assert _executed_volumes(mt5, rec["signal_id"]) == [0.10]


def test_executed_volume_invariant_to_declared_risk_fraction():
    vols = []
    for rf in (0.0010, 0.0025, 0.0100):
        ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp(), default_volume=0.10)
        rec = H.make_instruction(); rec["risk_fraction"] = rf
        H.produce(paths, rec); H.drain(ec)
        vols.append(_executed_volumes(mt5, rec["signal_id"]))
    assert vols == [[0.10], [0.10], [0.10]]        # execution size ignores risk_fraction


def test_default_volume_setting_alone_determines_size():
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp(), default_volume=0.50)
    rec = H.make_instruction(); rec["risk_fraction"] = 0.0025
    H.produce(paths, rec); H.drain(ec)
    assert _executed_volumes(mt5, rec["signal_id"]) == [0.50]   # operator constant wins


def test_instruction_schema_has_no_volume_field():
    assert "volume" not in REQUIRED_INSTRUCTION_FIELDS


def test_resolve_volume_falls_through_to_default():
    ec, _p, _l, _a, _m = H.build(tempfile.mkdtemp(), default_volume=0.10)
    assert ec._resolve_volume({"risk_fraction": 0.5}) == 0.10   # no volume -> default
    assert ec._resolve_volume({"volume": 0.03}) == 0.03         # (v1 never supplies one)
