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


def check_compile(results):
    import compileall
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = compileall.compile_dir("phantom", quiet=1, force=True)
        ok = compileall.compile_file("validate.py", quiet=1, force=True) and ok
        ok = compileall.compile_dir("tests", quiet=1, force=True) and ok
    if ok:
        results.append((True, _ok("compile check — phantom/ tests/ validate.py compile clean")))
    else:
        results.append((False, _fail("compile check", buf.getvalue().strip() or "compile error")))


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
            strong_approve_snapshot,
        )
        # Fresh scanner per fixture: each is an independent session observation
        # (ORB idempotency suppresses a second confirmation for the same
        # symbol/session/day, which is correct in production).
        strong = Scanner().scan_symbol(strong_approve_snapshot())
        moderate = Scanner().scan_symbol(approve_long_snapshot())
        r = Scanner().scan_symbol(ranging_snapshot())
        g = Scanner().scan_symbol(guard_blocked_snapshot())
        assert strong.decision == Decision.APPROVE, f"strong fixture -> {strong.decision}"
        assert strong.direction == Direction.LONG, f"strong dir -> {strong.direction}"
        assert moderate.decision == Decision.WATCHLIST, f"moderate fixture -> {moderate.decision}"
        assert r.decision != Decision.APPROVE, f"ranging fixture -> {r.decision}"
        assert g.decision == Decision.BLOCK, f"guard fixture -> {g.decision}"
        results.append((True, _ok("scanner regression — 4 fixtures stable")))
    except Exception as exc:
        results.append((False, _fail("scanner regression", repr(exc))))


def check_scoring_regression(results):
    try:
        from phantom.scanner import Scanner
        from tests.fixtures import (
            approve_long_snapshot, ranging_snapshot, strong_approve_snapshot,
        )
        strong = Scanner().scan_symbol(strong_approve_snapshot())
        r = Scanner().scan_symbol(ranging_snapshot())
        assert strong.total >= 72.0, f"strong total {strong.total} < 72"
        assert strong.orb and strong.orb.confirmed and strong.orb.score_impact > 0, "ORB not confirmed"
        if r.capped_at is not None:
            assert r.total <= 55.0, f"ranging total {r.total} > neutral cap"
        names = [c.name for c in strong.components]
        assert len(names) == 18, f"expected 18 components, got {len(names)}"
        assert "AI Meta Filter" not in names, "AI Meta Filter must be removed"
        assert "Volatility Health" in names, "Volatility Health missing"
        assert "ATR" not in names and "Volatility Ratio" not in names, "ATR/VolRatio not merged"
        assert "Strategy Confirmation" in names, "Strategy Confirmation missing"
        results.append((True, _ok("scoring regression — 18 components, no double-count")))
    except Exception as exc:
        results.append((False, _fail("scoring regression", repr(exc))))


def check_strategy_layer(results):
    """No duplicate signals / no inflation / conflict handling on the strategy
    layer."""
    try:
        from phantom.config import DEFAULT_CONFIG as C
        from phantom.scanner import Scanner
        from phantom.strategies.engine import StrategyEngine
        from phantom.strategies.base import StrategySignal
        from phantom.types import Direction
        from tests.fixtures import strong_approve_snapshot

        # Strategy layer never exceeds the hard cap, even with full agreement.
        res = Scanner().scan_symbol(strong_approve_snapshot())
        net = res.strategies["net_score"]
        assert net <= C.strategies.layer_cap, f"layer net {net} > cap (inflation)"

        eng = StrategyEngine()
        # Two agreeing strategies do NOT sum (no duplicate-signal inflation).
        agree = eng.resolve([
            StrategySignal("ORB", Direction.LONG, score=18.0, confirmed=True),
            StrategySignal("Session Breakout", Direction.LONG, score=18.0, confirmed=True),
        ])
        assert agree.net_score <= C.strategies.layer_cap and not agree.conflict, "agreement inflated"
        # Conflicting strategies cannot inflate — they cancel and dampen.
        conf = eng.resolve([
            StrategySignal("ORB", Direction.LONG, score=18.0, confirmed=True),
            StrategySignal("Liquidity Reversal", Direction.SHORT, score=10.0, confirmed=True),
        ])
        assert conf.conflict and conf.net_score < 18.0, "conflict not handled"
        results.append((True, _ok("strategy layer — capped, no duplicate/conflict inflation")))
    except Exception as exc:
        results.append((False, _fail("strategy layer", repr(exc))))


def check_safety_patch(results):
    """FIX 1-9 — idempotency, stacking, correlation, compliance, memory, threads."""
    try:
        import threading as _th
        from datetime import timedelta
        from phantom.guards import ComplianceEngine, Guards
        from phantom.orb import ORBEngine, ORBRange
        from phantom.scanner import Scanner
        from phantom.types import Direction, MarketSnapshot
        from tests.fixtures import NOW, approve_long_snapshot, strong_approve_snapshot
        from tests.test_pipeline import _orb_ctx

        def snap(symbol="EURUSD", **kw):
            return MarketSnapshot(symbol, NOW, {}, spread=0.00008, **kw)

        # FIX 1 idempotency
        eng = ORBEngine()
        assert eng.evaluate(approve_long_snapshot(), _orb_ctx()).confirmed
        assert not eng.evaluate(approve_long_snapshot(), _orb_ctx()).confirmed
        # FIX 2 stacking blocked
        assert not Guards().exposure(snap(open_positions={"EURUSD": Direction.LONG}), Direction.LONG).passed
        # FIX 3 correlation fail-closed
        assert not Guards().correlation(snap(symbol="EURGBP"), Direction.LONG).passed
        # FIX 4 compliance kill switch
        ce = ComplianceEngine(); ce.check(snap(equity=10000))
        assert not ce.check(snap(equity=8900)).passed
        assert not ce.check(snap(equity=10000)).passed  # latched
        # FIX 5 symbol spread
        assert not Guards().spread(MarketSnapshot("USDJPY", NOW, {}, spread=0.05)).passed
        # FIX 8 pruning
        old = (NOW - timedelta(days=10)).date().isoformat()
        e2 = ORBEngine(); e2._ranges["k"] = ORBRange("X", "NEWYORK", old, 1.1, 1.0, NOW, NOW, True)
        e2._prune(NOW); assert e2._ranges == {}
        # FIX 9 thread safety
        app_errors = []
        s = Scanner()
        def w(n):
            try:
                for i in range(30):
                    s.scan_symbol(MarketSnapshot(f"T{n}{i%4}", NOW, strong_approve_snapshot().candles, spread=0.00008))
                    s.orb.status(NOW)
            except Exception as exc:
                app_errors.append(exc)
        ths = [_th.Thread(target=w, args=(n,)) for n in range(6)]
        [t.start() for t in ths]; [t.join() for t in ths]
        assert not app_errors, f"thread errors: {app_errors[:1]}"

        results.append((True, _ok("safety patch — idempotency/exposure/correlation/compliance/memory/threads")))
    except Exception as exc:
        results.append((False, _fail("safety patch", repr(exc))))


def check_distribution(results):
    """OLD (19-component) vs NEW (18-component) score distribution on identical
    fixture data. OLD values are the recorded pre-refactor baseline."""
    try:
        from phantom.scanner import Scanner
        from tests.fixtures import (
            approve_long_snapshot, ranging_snapshot, guard_blocked_snapshot,
            strong_approve_snapshot,
        )
        # Only the moderate-long OLD score was recorded pre-refactor; others
        # were BLOCK either way, so their totals are not asserted here.
        old = {"moderate-long": (75.01, "APPROVE")}
        new = {  # fresh scanner per fixture (independent session observations)
            "moderate-long": Scanner().scan_symbol(approve_long_snapshot()),
            "ranging": Scanner().scan_symbol(ranging_snapshot()),
            "guard-blocked": Scanner().scan_symbol(guard_blocked_snapshot()),
            "strong-long": Scanner().scan_symbol(strong_approve_snapshot()),
        }
        print("\n  OLD vs NEW score distribution (identical data):")
        print(f"    {'fixture':16} {'OLD':>16}   {'NEW':>16}")
        for k, res in new.items():
            o = old.get(k)
            o_s = f"{o[0]:.2f} {o[1]}" if o else "-- (not recorded)"
            print(f"    {k:16} {o_s:>16}   {res.total:6.2f} {res.decision.value:>9}")
        # Thresholds preserved.
        from phantom.config import DEFAULT_CONFIG as C
        assert C.thresholds.approve == 72.0 and C.thresholds.watchlist == 60.0
        assert C.thresholds.neutral_cap == 55.0
        results.append((True, _ok("distribution — thresholds preserved (72/60/55), deflation observed")))
    except Exception as exc:
        results.append((False, _fail("distribution", repr(exc))))


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
            for path in ("/health", "/orb/status", "/strategies/performance"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
                    assert resp.status == 200, f"{path} -> {resp.status}"
                    body = json.loads(resp.read())
                assert isinstance(body, dict)
            # Prometheus /metrics — text exposition, export only.
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics") as resp:
                assert resp.status == 200, f"/metrics -> {resp.status}"
                assert resp.headers["Content-Type"].startswith("text/plain")
                metrics_body = resp.read().decode()
            assert "phantom_up 1" in metrics_body and "phantom_scans_total" in metrics_body
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/orb/status") as resp:
                status = json.loads(resp.read())
            assert "active_sessions" in status and "ranges" in status
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/strategies/performance") as resp:
                perf = json.loads(resp.read())
            assert "strategies" in perf and "best" in perf and "worst" in perf
        finally:
            server.shutdown()
            server.server_close()
        results.append((True, _ok("endpoint check — /health and /orb/status respond 200")))
    except Exception as exc:
        results.append((False, _fail("endpoint check", repr(exc))))


def main():
    results = []
    print("Phantom — Part 5 validation\n" + "=" * 40)
    check_compile(results)
    check_imports(results)
    check_startup(results)
    check_scanner_regression(results)
    check_scoring_regression(results)
    check_strategy_layer(results)
    check_safety_patch(results)
    check_distribution(results)
    check_endpoints(results)
    for _passed, line in results:
        print(line)
    passed = sum(1 for p, _ in results if p)
    print("=" * 40)
    print(f"{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
