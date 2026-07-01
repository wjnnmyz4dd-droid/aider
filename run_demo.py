#!/usr/bin/env python3
"""Small end-to-end demo: scan a sample symbol and print the decision plus the
ORB status the API would serve. No network, no orders."""

from __future__ import annotations

import json

from phantom.app import create_app
from tests.fixtures import NOW, approve_long_snapshot


def main():
    app = create_app()
    result = app.scan_symbol(approve_long_snapshot())

    print("=== SCAN RESULT ===")
    print(json.dumps({
        "symbol": result.symbol,
        "decision": result.decision.value,
        "direction": result.direction.value,
        "score": round(result.total, 2),
        "capped_at": result.capped_at,
    }, indent=2))

    print("\n=== COMPONENTS ===")
    for c in result.components:
        tag = " [BLOCK]" if c.blocking else ""
        fail = " FAILED" if c.failed else ""
        print(f"  {c.points:6.2f}  {c.name:22}{tag}{fail}  {c.detail}")

    print("\n=== GET /orb/status ===")
    print(json.dumps(app.orb.status(NOW), indent=2, default=str))


if __name__ == "__main__":
    main()
