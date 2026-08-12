"""Read-only strategy-session capability contract (Phase 9A).

States what the CURRENT frozen strategy actually supports, so unsupported session
selections fail closed (or are reported) instead of silently pretending a London
Opening-Range engine is a Sydney/Tokyo/New-York strategy. It changes no strategy
logic — it only describes truth used by the producer/compliance session gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import (SessionReason, SYDNEY, TOKYO, LONDON, NEW_YORK,
                    SYDNEY_TOKYO, TOKYO_LONDON, LONDON_NEW_YORK)


class StrategySessionPolicy:
    FAIL_CLOSED = "FAIL_CLOSED"      # unsupported active session -> not eligible
    REPORT_ONLY = "REPORT_ONLY"     # eligible, but snapshot flags unsupported


@dataclass(frozen=True)
class StrategyCapability:
    strategy_id: str
    strategy_version: str
    supported_session_models: tuple        # e.g. ("LONDON_OPENING_RANGE",)
    opening_range_session: str             # the session whose open the OR is built on
    execution_timeframe: str
    higher_timeframes: tuple
    supports_multi_session_scanning: bool
    supports_overlap_specific_setup: bool
    strategy_supported_sessions: frozenset  # sessions the engine can actually trade
    strategy_supported_overlaps: frozenset  # overlaps eligible under the frozen rules

    def as_dict(self):
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "supported_session_models": list(self.supported_session_models),
            "opening_range_session": self.opening_range_session,
            "execution_timeframe": self.execution_timeframe,
            "higher_timeframes": list(self.higher_timeframes),
            "supports_multi_session_scanning": self.supports_multi_session_scanning,
            "supports_overlap_specific_setup": self.supports_overlap_specific_setup,
            "strategy_supported_sessions": sorted(self.strategy_supported_sessions),
            "strategy_supported_overlaps": sorted(self.strategy_supported_overlaps),
        }


# PR-4A: the Session Edge Swing-ORB engine now applies the SAME ORB methodology
# independently to every supported session (Sydney/Tokyo/London/New-York), each
# with its own session clock (session_window_utc + a SessionProfile). Multi-session
# scanning is genuinely supported: the producer fans out one independent ORB
# evaluation per enabled session profile. Overlap-specific setups are still NOT a
# distinct strategy — an overlap is just two independently-identified session
# evaluations, so overlap-specific setup support remains False.
SESSION_ORB_CAPABILITY = StrategyCapability(
    strategy_id="forex_swing_orb",
    strategy_version="swing_orb.v1.4.0",
    supported_session_models=("SESSION_OPENING_RANGE",),
    opening_range_session=LONDON,                        # the frozen reference profile
    execution_timeframe="M15",
    higher_timeframes=("H4", "D1"),
    supports_multi_session_scanning=True,
    supports_overlap_specific_setup=False,
    strategy_supported_sessions=frozenset({SYDNEY, TOKYO, LONDON, NEW_YORK}),
    strategy_supported_overlaps=frozenset({SYDNEY_TOKYO, TOKYO_LONDON, LONDON_NEW_YORK}),
)

# Backward-compatible alias (older imports/tests referenced the London-only name).
LONDON_ORB_CAPABILITY = SESSION_ORB_CAPABILITY


def strategy_session_support(capability, kind, ident, active_sessions, active_overlaps):
    """Is the eligible session/overlap actually supported by the frozen strategy?

    Returns (supported: bool, reason). ``kind`` is "session" or "overlap".
    Overlap support additionally requires the London OR session to be present
    (LONDON_NEW_YORK is only valid once London is/was active)."""
    if capability is None:
        return True, None                      # no capability declared -> do not gate on it
    if kind == "session":
        if ident in capability.strategy_supported_sessions:
            return True, None
        return False, SessionReason.STRATEGY_SESSION_UNSUPPORTED
    # overlap
    if ident in capability.strategy_supported_overlaps:
        # LONDON_NEW_YORK requires London to be part of the overlap membership
        if ident == LONDON_NEW_YORK and LONDON in (active_sessions or ()):
            return True, None
        if ident == LONDON_NEW_YORK:
            return False, SessionReason.STRATEGY_OVERLAP_UNSUPPORTED
        return True, None
    return False, SessionReason.STRATEGY_OVERLAP_UNSUPPORTED
