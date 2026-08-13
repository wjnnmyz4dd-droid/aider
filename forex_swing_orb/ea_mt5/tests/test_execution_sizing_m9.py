"""PR-3J / M9 (EA half) — the EA executes the AUTHORITATIVE instruction volume.

The frozen v1 gap is closed: volume is a required schema-3 field, sized upstream and
proven within risk-per-trade by compliance. The execution adapter executes it
VERBATIM — no DefaultVolume substitution, no risk math, no upsizing. A missing or
step-misaligned volume fails closed. Retries/recovery reuse the exact same volume.
"""

from __future__ import annotations

import tempfile

from forex_swing_orb.bridge.contract import ResultState, REQUIRED_INSTRUCTION_FIELDS
from forex_swing_orb.ea_mt5 import mock_mt5
from forex_swing_orb.validation import harness as H


def _executed_volumes(mt5, sid):
    return sorted(p.volume for p in mt5.positions.values() if p.comment == sid)


def test_executes_authoritative_instruction_volume():
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp(), default_volume=0.10)
    rec = H.make_instruction(volume=0.37)
    mt5.add_symbol("EURUSD", volume_step=0.01)      # 0.37 is on 0.01 step
    H.produce(paths, rec)
    r = H.drain(ec)[0]
    assert r["status"] == ResultState.EXECUTED
    assert _executed_volumes(mt5, rec["signal_id"]) == [0.37]   # verbatim, not 0.10


def test_volume_is_required_in_production_schema():
    assert "volume" in REQUIRED_INSTRUCTION_FIELDS


def test_missing_volume_rejected_no_default_substitution():
    # a record with volume=None must fail closed (bridge/EA), never fall back to
    # the operator DefaultVolume (0.10).
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp(), default_volume=0.10)
    rec = H.make_instruction(volume=None)
    H.produce(paths, rec)
    r = H.drain(ec)[0]
    assert r["status"] != ResultState.EXECUTED
    assert len(mt5.order_log) == 0                  # no order ever sent


def test_off_step_volume_rejected_no_upsizing():
    # 0.015 with a 0.01 step is off-step -> REJECT (never rounded up to 0.02).
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp())
    for s in H.SYMBOLS:
        mt5.symbols[s].volume_step = 0.01
    rec = H.make_instruction(volume=0.015)
    H.produce(paths, rec)
    r = H.drain(ec)[0]
    assert r["status"] == ResultState.EXECUTION_FAILED
    assert len(mt5.order_log) == 0                  # rejected, not upsized/sent


def test_resolve_volume_has_no_default_fallback():
    ec, _p, _l, _a, _m = H.build(tempfile.mkdtemp(), default_volume=0.10)
    assert ec._resolve_volume({"volume": 0.25}) == 0.25
    assert ec._resolve_volume({"risk_fraction": 0.5}) is None   # no volume -> None (not 0.10)


# --------------------------------------------------------------------------- #
# property F — retry cannot change volume; property G — no execution beyond approved
# --------------------------------------------------------------------------- #
def test_propF_retry_reuses_exact_volume():
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp())
    mt5.script(mock_mt5.TRADE_RETCODE_REQUOTE)      # one transient retry, then success
    rec = H.make_instruction(volume=0.20)
    H.produce(paths, rec)
    H.drain(ec)
    # every order_send in the retry sequence used the SAME approved volume
    assert {o["volume"] for o in mt5.order_log} == {0.20}


def test_propG_executed_volume_never_exceeds_approved():
    ec, paths, _l, _a, mt5 = H.build(tempfile.mkdtemp())
    rec = H.make_instruction(volume=0.20)
    H.produce(paths, rec); H.drain(ec)
    assert all(v <= 0.20 for v in _executed_volumes(mt5, rec["signal_id"]))
