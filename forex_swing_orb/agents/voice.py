"""Outward Session Edge voice interface (DESIGN ONLY — not implemented in 4A).

One single outward voice for Session Edge. Agents operate internally and never
speak individually. This module freezes the *interface* the user will later reach
(overall summary, individual agent report, reason for block, reason for no trade,
trade explanation, market status). Implementation belongs to a later phase; every
method here fails closed with NotImplementedError so nothing ships accidentally.

The voice is a read-only presentation surface over decisions/explanations already
produced deterministically. It has no authority to decide, trade, or modify.
"""

from __future__ import annotations


class SessionEdgeVoice:
    """The single outward voice contract. Later phases provide the implementation
    (backed by the Explainability Service + Memory), not per-agent voices."""

    interface_version = "0.1.0"

    _NOT_YET = "Session Edge voice is designed but not implemented until a later phase."

    def overall_summary(self, correlation_id):
        raise NotImplementedError(self._NOT_YET)

    def agent_report(self, correlation_id, agent_id):
        raise NotImplementedError(self._NOT_YET)

    def reason_for_block(self, correlation_id):
        raise NotImplementedError(self._NOT_YET)

    def reason_for_no_trade(self, correlation_id):
        raise NotImplementedError(self._NOT_YET)

    def trade_explanation(self, correlation_id):
        raise NotImplementedError(self._NOT_YET)

    def market_status(self, symbol):
        raise NotImplementedError(self._NOT_YET)
