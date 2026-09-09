"""Operator risk-profile / sizing-mode front-end (zero-friction UX) — NOT a sizing
or risk authority.

This is the risk-configuration sibling of :mod:`runtime.session_selection`: it makes
"how much risk per trade?" easy to choose and remember WITHOUT becoming a second
sizing or compliance authority. The single authorities are unchanged:

  * PR-3J ``compliance.sizing.allowable_volume`` remains the SOLE position sizer;
  * the compliance RISK gate remains the SOLE risk authority and independently
    re-proves ``risk_fraction <= max_risk_per_trade_pct`` and the monetary
    loss-at-stop for the sized volume;
  * H-1 aggregate committed-risk accounting is unchanged (it reads the SAME
    ``risk_fraction`` off the written instruction).

All this module does is resolve a human-friendly profile to ONE explicit, bounded
``risk_fraction`` (a POLICY input the compliance gate already treats as a cap, never
as proof), choose a sizing MODE, persist the choice (like the terminal / capital
base / session selection already persist), and hand the resolved fraction to the
producer via a single env var. It changes NO signal, setup, trend, breakout/retest,
news, session, or FTMO logic — only how much of the ALREADY-permitted risk budget a
trade uses. The capital BASIS stays the pinned funded ``initial_balance`` (the
existing capital contract; H-1- and FTMO-floor-consistent) — this module never
introduces a live-equity basis.
"""

from __future__ import annotations

from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from ..compliance.contract import FtmoConfig, finite

RISK_SCHEMA_VERSION = 1
RISK_FILE = "risk_profile.json"

# The canonical per-trade risk ceiling. Sourced from the ONE compliance overlay
# (FtmoConfig.max_risk_per_trade_pct) so this front-end can never drift above the
# authority that will enforce it at runtime anyway (defense in depth).
CEILING_RISK_FRACTION = FtmoConfig().max_risk_per_trade_pct   # 0.01 (1%)

# Named profiles -> explicit, documented per-trade risk fractions, each <= ceiling.
# MODERATE is the recommended default. AGGRESSIVE equals the ceiling (equality is
# permitted by the compliance gate). These are RISK fractions only; they do not
# touch strategy/setup/trend/news/session/FTMO logic.
PROFILE_FRACTIONS = {
    "CONSERVATIVE": 0.0025,     # 0.25%
    "MODERATE": 0.005,          # 0.50%  (default)
    "AGGRESSIVE": 0.01,         # 1.00%  (== ceiling)
}
DEFAULT_PROFILE = "MODERATE"
NAMED_PROFILES = tuple(PROFILE_FRACTIONS)           # excludes CUSTOM
ALL_PROFILES = NAMED_PROFILES + ("CUSTOM",)

# Sizing modes. ADAPTIVE = risk-based via PR-3J (the default). CUSTOM_RISK = an
# explicit per-trade risk percentage (still risk-based, still PR-3J, still bounded).
# There is deliberately NO raw fixed-lot mode: a user-supplied lot must never bypass
# the safe calculated maximum, so lots are always derived by PR-3J from risk.
SIZING_ADAPTIVE = "ADAPTIVE"
SIZING_CUSTOM_RISK = "CUSTOM_RISK"
ALL_SIZING_MODES = (SIZING_ADAPTIVE, SIZING_CUSTOM_RISK)


class RiskProfileError(ValueError):
    """Raised when a risk selection cannot be resolved safely (fail closed) — unknown
    profile, out-of-bounds custom fraction, or a corrupt persisted file."""


def resolve_fraction(profile, custom_fraction=None):
    """Map a profile (and optional custom fraction) to an explicit ``risk_fraction``
    and sizing mode. Returns ``(profile, risk_fraction, sizing_mode)``. Fails closed
    on an unknown profile or an out-of-bounds/invalid CUSTOM fraction — NEVER silently
    substitutes a different risk level, and NEVER exceeds the ceiling."""
    if profile is None:
        raise RiskProfileError("no risk profile selected")
    p = str(profile).strip().upper()
    if p in PROFILE_FRACTIONS:
        return p, PROFILE_FRACTIONS[p], SIZING_ADAPTIVE
    if p == "CUSTOM":
        rf = finite(custom_fraction)
        if rf is None or rf <= 0:
            raise RiskProfileError(
                "CUSTOM risk profile requires a positive risk fraction "
                "(e.g. 0.004 for 0.4%)")
        if rf > CEILING_RISK_FRACTION + 1e-12:
            raise RiskProfileError(
                f"CUSTOM risk fraction {rf} exceeds the ceiling "
                f"{CEILING_RISK_FRACTION} (max_risk_per_trade_pct); refused")
        return "CUSTOM", float(rf), SIZING_CUSTOM_RISK
    raise RiskProfileError(
        f"unknown risk profile: {profile!r} (supported: {list(ALL_PROFILES)})")


def store_path(home=None):
    """Stable, pre-connect persistence location — the same ~/.session_edge home the
    terminal / session selections use."""
    base = Path(home) if home is not None else Path.home()
    return base / ".session_edge" / RISK_FILE


def load_persisted(path):
    """Return the persisted ``(profile, risk_fraction, sizing_mode)`` or None if none
    saved yet. A file that EXISTS but is corrupt/out-of-bounds FAILS CLOSED (raises)
    rather than silently reverting to a different risk level; an absent file is
    'no selection yet' (caller may use its default)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    ok, obj = serialize.loads(text)
    if not ok or not isinstance(obj, dict):
        raise RiskProfileError(
            f"persisted risk profile is corrupt at {path} "
            f"(re-select with --risk-profile to repair)")
    # re-resolve through the SAME validator so a tampered/out-of-bounds stored value
    # fails closed exactly like a fresh selection.
    return resolve_fraction(obj.get("profile"), obj.get("risk_fraction"))


def persist(path, profile, risk_fraction, sizing_mode, now_iso):
    """Atomically record the (already-resolved) risk selection for next run."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, serialize.canonical_json({
        "schema_version": RISK_SCHEMA_VERSION,
        "profile": profile,
        "risk_fraction": risk_fraction,
        "sizing_mode": sizing_mode,
        "saved_at": now_iso,
    }))
    return (profile, risk_fraction, sizing_mode)


def resolve(cli_profile, cli_custom_fraction, path, *, now_iso=None, persist_cli=True):
    """Resolve the effective risk selection. Deterministic precedence:

        explicit CLI profile  >  persisted selection  >  default (MODERATE)

    Returns ``(profile, risk_fraction, sizing_mode, source)`` where source is one of
    'cli' | 'persisted' | 'default'. An explicit CLI selection is (by default)
    persisted so the next plain restart reuses it. A present-but-invalid persisted
    file fails closed. Never silently substitutes a different risk level."""
    if cli_profile not in (None, ""):
        profile, rf, mode = resolve_fraction(cli_profile, cli_custom_fraction)
        if persist_cli:
            persist(path, profile, rf, mode, now_iso or "")
        return profile, rf, mode, "cli"
    persisted = load_persisted(path)                 # may raise on corrupt (fail closed)
    if persisted:
        return persisted[0], persisted[1], persisted[2], "persisted"
    profile, rf, mode = resolve_fraction(DEFAULT_PROFILE)
    return profile, rf, mode, "default"
