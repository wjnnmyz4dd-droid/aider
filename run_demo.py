#!/usr/bin/env python3
"""Small end-to-end demo: scan a sample symbol and print the decision plus the
ORB status the API would serve. No network, no orders."""

from __future__ import annotations

import json

from phantom.app import create_app
from tests.fixtures import NOW, strong_approve_snapshot


def main():
    app = create_app()
    result = app.scan_symbol(strong_approve_snapshot())

    print("=== SCAN RESULT ===")
    print(json.dumps({
        "symbol": result.symbol,
        "decision": result.decision.value,
        "direction": result.direction.value,
        "score": round(result.total, 2),
        "capped_at": result.capped_at,
    }, indent=2))

    print("\n=== COMPONENTS (18) ===")
    for c in result.components:
        tag = " [BLOCK]" if c.blocking else ""
        fail = " FAILED" if c.failed else ""
        print(f"  {c.points:6.2f}  {c.name:22}{tag}{fail}  {c.detail}")

    print("\n=== STRATEGY LAYER ===")
    st = result.strategies
    print(f"  net={st['net_score']}  direction={st['direction']}  conflict={st['conflict']}")
    for sig in st["signals"]:
        print(f"    {sig['name']:20} {sig['direction']:5} score={sig['score']:5} "
              f"pen={sig['penalty']:5}  {sig['reason']}")

    print("\n=== TRADE THESIS SUMMARY (informational only) ===")
    print(" ", result.thesis)

    # Illustrative closed-trade results (would come from the execution layer).
    for s, pnl in [("ORB", 120), ("ORB", -40), ("Session Breakout", 60),
                   ("Liquidity Reversal", -25), ("Liquidity Reversal", 90)]:
        app.record_trade(s, pnl)
    print("\n=== GET /strategies/performance ===")
    print(json.dumps(app.performance.panel(), indent=2, default=str))

    print("\n=== GET /orb/status ===")
    print(json.dumps(app.orb.status(NOW), indent=2, default=str))


if __name__ == "__main__":
    main()
