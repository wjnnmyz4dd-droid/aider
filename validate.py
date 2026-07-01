#!/usr/bin/env python3
"""Part 5 validation suite.

Runs five checks and prints a pass/fail report:
  1. import check          — every module imports cleanly
  2. startup check         — the app factory builds a working app
  3. scanner regression    — decisions on fixed fixtures are stable
  4. scoring regression    — score relationships hold
  5. endpoint check        — GET /orb/status and /health respond 200

Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request


def _ok(label: str) -> str:
    return f"  PASS  {label}"


def _fail(label: str, detail: str) -> str:
    return f"  FAIL  {label} :: {detail}"


def check_imports(results):
    try:
        import phantom  # noqa
        from phantom import (  # noqa
            api, app, config, guards, indicators, logging_sink, orb,
            regime, scanner, scorer, structure, types,
        )
        results.append((True, _ok("import check — all modules import")))
    except Exception as exc:  # pragma: no cover
        results.append((False, _fail("import check", repr(exc))))


def check_startup(results):
    try:
        from phantom.app import create_app
        app = create_app()
        assert app.scanner is not None and app.orb is not None and app.sink is not None
        results.append((True, _ok("startup check — app factory builds pipeline")))
    except Exception as exc:
        results.append((False, _fail("startup check", repr(exc))))


def check_scanner_regression(results):
    try:
        from phantom.scanner import Scanner
        from phantom.types import Decision, Direction
        from tests.fixtures import (
            approve_long_snapshot, guard_blocked_snapshot, ranging_snapshot,
        )
        s = Scanner()
        a = s.scan_symbol(approve_long_snapshot())
        r = s.scan_symbol(ranging_snapshot())
        g = s.scan_symbol(guard_blocked_snapshot())
        assert a.decision == Decision.APPROVE, f"approve fixture -> {a.decision}"
        assert a.direction == Direction.LONG, f"approve dir -> {a.direction}"
        assert r.decision != Decision.APPROVE, f"ranging fixture -> {r.decision}"
        assert g.decision == Decision.BLOCK, f"guard fixture -> {g.decision}"
        results.append((True, _ok("scanner regression — 3 fixtures stable")))
    except Exception as exc:
        results.append((False, _fail("scanner regression", repr(exc))))


def check_scoring_regression(results):
    try:
        from phantom.scanner import Scanner
        from tests.fixtures import approve_long_snapshot, ranging_snapshot
        s = Scanner()
        a = s.scan_symbol(approve_long_snapshot())
        r = s.scan_symbol(ranging_snapshot())
        assert a.total >= 72.0, f"approve total {a.total} < 72"
        assert a.orb and a.orb.confirmed and a.orb.score_impact > 0, "ORB not confirmed"
        if r.capped_at is not None:
            assert r.total <= 55.0, f"ranging total {r.total} > neutral cap"
        names = {c.name for c in a.components}
        assert len(names) >= 19, f"only {len(names)} components"
        results.append((True, _ok("scoring regression — totals & ORB impact correct")))
    except Exception as exc:
        results.append((False, _fail("scoring regression", repr(exc))))


def check_endpoints(results):
    try:
        from phantom.app import create_app
        from phantom.api import serve, registered_routes
        from tests.fixtures import approve_long_snapshot
        assert "GET /orb/status" in registered_routes()
        app = create_app()
        app.scan_symbol(approve_long_snapshot())
        server = serve(app, host="127.0.0.1", port=0)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            for path in ("/health", "/orb/status"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
                    assert resp.status == 200, f"{path} -> {resp.status}"
                    body = json.loads(resp.read())
                assert isinstance(body, dict)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/orb/status") as resp:
                status = json.loads(resp.read())
            assert "active_sessions" in status and "ranges" in status
        finally:
            server.shutdown()
            server.server_close()
        results.append((True, _ok("endpoint check — /health and /orb/status respond 200")))
    except Exception as exc:
        results.append((False, _fail("endpoint check", repr(exc))))


def main():
    results = []
    print("Phantom — Part 5 validation\n" + "=" * 40)
    check_imports(results)
    check_startup(results)
    check_scanner_regression(results)
    check_scoring_regression(results)
    check_endpoints(results)
    for _passed, line in results:
        print(line)
    passed = sum(1 for p, _ in results if p)
    print("=" * 40)
    print(f"{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
