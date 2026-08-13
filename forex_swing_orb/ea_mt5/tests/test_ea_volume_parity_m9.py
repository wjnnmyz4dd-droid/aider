"""PR-3J / M9 — P-1 active-path parity for the authoritative volume contract.

Reads the SHIPPED .mq5 and asserts the EA (a) requires ``volume`` as a schema field,
(b) parses it in the active validator, (c) executes THAT volume verbatim (never the
DefaultVolume input) in the active order call, and (d) validates it against live
broker min/max/step. Each guard has an adversarial mutation proving it catches drift.
Source parity only (not MetaEditor compile / broker execution — [ENV]).
"""

from __future__ import annotations

import re

import _ea_parity as P

E = P.entry_source()


# --------------------------------------------------------------------------- #
# guard predicates (scoped to the active, comment-stripped bodies)
# --------------------------------------------------------------------------- #
def _volume_required_field(src):
    return "volume" in P.need_fields(src) and "volume" in P.EXPECTED_EA_NEED


def _volume_parsed_in_validator(src):
    v = P.entry_validator_body(src)
    return re.search(r'JsonGetDouble\(\s*json\s*,\s*"volume"', v) is not None


def _executes_instruction_volume(src):
    d = P.entry_dispatch_body(src)
    assigned = re.search(r'double\s+vol\s*=\s*volume\s*;', d) is not None
    buy = re.search(r'g_trade\.Buy\(\s*vol\s*,', d) is not None
    sell = re.search(r'g_trade\.Sell\(\s*vol\s*,', d) is not None
    return assigned and buy and sell


def _no_default_volume_in_dispatch(src):
    # DefaultVolume must never drive the active execution path (it is a deprecated,
    # inert input declared outside Execute).
    return "DefaultVolume" not in P.entry_dispatch_body(src)


def _volume_validated_against_broker(src):
    d = P.entry_dispatch_body(src)
    return ("SYMBOL_VOLUME_STEP" in d
            and re.search(r'MathRound\(\(vol-vmin\)/vstep\)', d) is not None
            and '"X_INVALID_VOLUME"' in d)


# --------------------------------------------------------------------------- #
# canonical (shipped source must satisfy every guard)
# --------------------------------------------------------------------------- #
def test_volume_is_required_field():
    assert _volume_required_field(E)


def test_volume_parsed_in_active_validator():
    assert _volume_parsed_in_validator(E)


def test_active_path_executes_instruction_volume():
    assert _executes_instruction_volume(E)


def test_no_default_volume_substitution_in_active_path():
    assert _no_default_volume_in_dispatch(E)


def test_volume_validated_against_broker_constraints():
    assert _volume_validated_against_broker(E)


def test_validation_precedes_order_dispatch():
    # the validator (which parses/checks volume) runs before any Buy/Sell
    d = P.entry_dispatch_body(E)
    assert P.occurs_before(d, r"\bValidateInstruction\s*\(",
                           [r"g_trade\.Buy\(", r"g_trade\.Sell\("])


# --------------------------------------------------------------------------- #
# adversarial mutations — each MUST break a guard
# --------------------------------------------------------------------------- #
def test_mutation_remove_volume_need_field_caught():
    mut = E.replace('"volume",', '', 1)              # drop volume from need[]
    assert not _volume_required_field(mut)


def test_mutation_substitute_default_volume_caught():
    mut = E.replace("double vol = volume;", "double vol = DefaultVolume;")
    assert not _executes_instruction_volume(mut) or not _no_default_volume_in_dispatch(mut)


def test_mutation_fixed_lot_order_call_caught():
    mut = E.replace("g_trade.Buy(vol,", "g_trade.Buy(0.10,")
    assert not _executes_instruction_volume(mut)     # order no longer uses the sized vol


def test_mutation_remove_volume_validation_caught():
    mut = E.replace(
        "(vstep > 0 && MathAbs(MathRound((vol-vmin)/vstep)*vstep + vmin - vol) > vstep*1e-6)",
        "false")
    assert not _volume_validated_against_broker(mut)


def test_mutation_remove_volume_parse_caught():
    mut = E.replace('volume = JsonGetDouble(json, "volume", ok);', "")
    assert not _volume_parsed_in_validator(mut)
