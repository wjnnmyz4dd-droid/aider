"""User risk-profile front-end (runtime.risk_profile) + config integration.

Proves the profile resolver is deterministic, bounded by the compliance ceiling,
fail-closed on bad input/corrupt persistence, and correctly persisted/reloaded — and
that RuntimeConfig validates the resolved risk_fraction against the SAME ceiling.
This module is a front-end only: PR-3J stays the sole sizer (proven in the producer
adaptive-sizing suite); here we only prove the configuration contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.runtime import risk_profile as R  # noqa: E402
from forex_swing_orb.runtime import config as C  # noqa: E402


# --- profile resolution (items 1-4) ----------------------------------------
def test_named_profiles_resolve_to_documented_fractions():
    assert R.resolve_fraction("CONSERVATIVE") == ("CONSERVATIVE", 0.0025, R.SIZING_ADAPTIVE)
    assert R.resolve_fraction("MODERATE") == ("MODERATE", 0.005, R.SIZING_ADAPTIVE)
    assert R.resolve_fraction("AGGRESSIVE") == ("AGGRESSIVE", 0.01, R.SIZING_ADAPTIVE)
    # case-insensitive
    assert R.resolve_fraction("moderate")[0] == "MODERATE"


def test_moderate_is_default():
    prof, rf, mode, source = R.resolve(None, None, "/nonexistent/does/not/exist.json")
    assert prof == "MODERATE" and rf == 0.005 and mode == R.SIZING_ADAPTIVE
    assert source == "default"


def test_custom_within_bounds_resolves():
    assert R.resolve_fraction("CUSTOM", 0.004) == ("CUSTOM", 0.004, R.SIZING_CUSTOM_RISK)


def test_custom_bounds_fail_closed():
    with pytest.raises(R.RiskProfileError):
        R.resolve_fraction("CUSTOM", None)              # missing
    with pytest.raises(R.RiskProfileError):
        R.resolve_fraction("CUSTOM", 0)                 # non-positive
    with pytest.raises(R.RiskProfileError):
        R.resolve_fraction("CUSTOM", -0.01)             # negative
    with pytest.raises(R.RiskProfileError):
        R.resolve_fraction("CUSTOM", 0.02)              # above ceiling (0.01)


def test_aggressive_equals_ceiling_but_never_exceeds():
    _, rf, _ = R.resolve_fraction("AGGRESSIVE")
    assert rf == R.CEILING_RISK_FRACTION
    for _, frac in R.PROFILE_FRACTIONS.items():
        assert frac <= R.CEILING_RISK_FRACTION + 1e-12


def test_unknown_profile_fails_closed():
    with pytest.raises(R.RiskProfileError):
        R.resolve_fraction("YOLO")
    with pytest.raises(R.RiskProfileError):
        R.resolve_fraction(None)


# --- determinism (items 7-8) -----------------------------------------------
def test_resolution_is_deterministic_no_randomness():
    results = {R.resolve_fraction("MODERATE") for _ in range(20)}
    assert results == {("MODERATE", 0.005, R.SIZING_ADAPTIVE)}   # identical every time


# --- persistence + precedence (items 15, 28) -------------------------------
def test_persist_and_reload_roundtrip(tmp_path):
    p = tmp_path / ".session_edge" / "risk_profile.json"
    R.persist(p, "CONSERVATIVE", 0.0025, R.SIZING_ADAPTIVE, "2026-08-27T00:00:00Z")
    assert R.load_persisted(p) == ("CONSERVATIVE", 0.0025, R.SIZING_ADAPTIVE)


def test_precedence_cli_over_persisted_over_default(tmp_path):
    p = tmp_path / "risk.json"
    # persisted AGGRESSIVE
    R.persist(p, "AGGRESSIVE", 0.01, R.SIZING_ADAPTIVE, "t")
    # explicit CLI wins and re-persists
    prof, rf, mode, src = R.resolve("CONSERVATIVE", None, p, now_iso="t")
    assert (prof, rf, src) == ("CONSERVATIVE", 0.0025, "cli")
    # next plain restart reuses the persisted CLI choice
    prof2, rf2, _, src2 = R.resolve(None, None, p)
    assert (prof2, rf2, src2) == ("CONSERVATIVE", 0.0025, "persisted")


def test_restart_does_not_silently_revert(tmp_path):
    p = tmp_path / "risk.json"
    R.resolve("AGGRESSIVE", None, p, now_iso="t")        # user selects + persists
    # a plain restart must reproduce AGGRESSIVE, never fall back to MODERATE
    prof, rf, _, src = R.resolve(None, None, p)
    assert prof == "AGGRESSIVE" and rf == 0.01 and src == "persisted"


def test_corrupt_persisted_fails_closed(tmp_path):
    p = tmp_path / "risk.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(R.RiskProfileError):
        R.load_persisted(p)
    # an out-of-bounds stored fraction also fails closed (re-validated on load)
    p.write_text('{"profile": "CUSTOM", "risk_fraction": 0.99}', encoding="utf-8")
    with pytest.raises(R.RiskProfileError):
        R.load_persisted(p)


# --- RuntimeConfig integration (items 14, 26 at config layer) --------------
def _base_env(**over):
    env = {
        "SESSION_EDGE_BRIDGE_ROOT": "/tmp/se/bridge",
        "SESSION_EDGE_RUNTIME_DIR": "/tmp/se/rt",
        "SESSION_EDGE_SYMBOLS": "EURUSD.FX",
        "SESSION_EDGE_INITIAL_BALANCE": "100000",
        "SESSION_EDGE_ACCOUNT_CURRENCY": "USD",
        "SESSION_EDGE_FTMO_RULE_SOURCE": "ftmo.com (2-Step)",
        "SESSION_EDGE_FTMO_RULE_VERIFIED_AT": "2026-08-05",
        "SESSION_EDGE_FTMO_PROFILE_VERIFIED": "true",
        "SESSION_EDGE_NEWS_FILE": "/tmp/se/news.json",
        "SESSION_EDGE_OVERLAP_MODE": "ALLOW",
    }
    env.update(over)
    return env


def test_config_defaults_moderate_no_fraction_override():
    cfg = C.load_config(env=_base_env())
    assert cfg.risk_profile == "MODERATE" and cfg.sizing_mode == "ADAPTIVE"
    assert cfg.risk_fraction is None            # None -> engine default (backward compatible)
    assert cfg.public_dict()["risk_profile"] == "MODERATE"


def test_config_accepts_valid_fraction():
    cfg = C.load_config(env=_base_env(SESSION_EDGE_RISK_FRACTION="0.005",
                                      SESSION_EDGE_RISK_PROFILE="MODERATE"))
    assert cfg.risk_fraction == 0.005


def test_config_rejects_fraction_over_ceiling():
    with pytest.raises(C.ConfigError):
        C.load_config(env=_base_env(SESSION_EDGE_RISK_FRACTION="0.02"))   # > 0.01 ceiling


def test_config_rejects_nonpositive_fraction():
    with pytest.raises(C.ConfigError):
        C.load_config(env=_base_env(SESSION_EDGE_RISK_FRACTION="0"))
