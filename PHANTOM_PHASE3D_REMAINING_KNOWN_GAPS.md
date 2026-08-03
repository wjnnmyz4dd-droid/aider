# Phase 3D — Remaining Known Gaps

Consolidates every gap discovered or still open after Phase 3D validation.
None of these were fixed in this phase — per the phase's explicit
instruction, code changes were reserved for verified defects only, and
none of the items below is a defect (incorrect behavior); all are scope
boundaries or visibility limitations.

1. **No persisted account day-start/peak/lock tracking.**
   `_build_compliance_account_state()` (`deployment_windows/start.py`)
   maps the EA-reported balance onto `compliance_engine.AccountState`, but
   `daily_starting_balance`/`peak_balance` both mirror the *current*
   balance and `compliance_lock` always starts unlocked — there is no
   persistence of yesterday's starting balance or intraday peak across
   cycles or restarts. This was explicitly out of ADR-023's original scope
   and not reopened by Amendment 1. **Consequence:** Compliance Engine's
   daily-loss and drawdown gates cannot yet enforce real prop-firm rules
   correctly across a multi-day funded account — this must be closed
   before funded deployment.

2. **No multi-provider news failover.** No Trading Economics
   primary/Forex Factory backup provider exists in this codebase; the only
   real news-trust signal is `news_feed_trusted`
   (`MarketIntelligenceConfig`). Documented in `KNOWN_GAPS.md` §2,
   unchanged by this phase.

3. **`runtime_audit_record` structured fields are not visible in text
   logs.** The values (`cycle_id`, `outcome`, `stage_reached`,
   `duration_ms`, `stage_timings`) are computed correctly — verified this
   phase via direct in-process measurement — but `start.py`'s log
   `Formatter` doesn't reference the `extra` dict, so the log file only
   shows the bare message. Purely a visibility gap; the underlying
   runtime behavior is correct.

4. **Real MT5/Windows behavior not exercised in this sandbox.** Everything
   in the MT5 Demo Validation Report was verified via a Python HTTP
   simulator against the real Bridge/engine code running on Linux. Never
   exercised in this phase: MetaEditor compilation of the actual
   `TitanProtocolEA.mq5`, real broker tick/bar delivery timing and
   quality, MT5 terminal restart/reconnect behavior, and Windows
   `WebRequest` allow-listing. These require the user's own hands-on demo
   account verification before any funded consideration.

5. **Bridge-unavailable scenario reasoned by code inspection, not
   re-executed live this phase.** `SendClosedBar()`/`SendTick()` share the
   same retrying `HttpPost()` helper as every pre-existing message type,
   so no new failure mode was introduced — but an active "kill the bridge
   process mid-session, confirm the EA queues/retries/logs correctly" test
   was not run in this phase.

6. **A genuinely qualifying Strategy signal was not produced this
   phase**, so Risk Engine and Compliance Engine decisions were not
   observed end-to-end against live-shaped data in this sandbox (only
   proven reachable via code inspection + successful wiring through
   Evidence/Market Intelligence/Strategy). Engine-level correctness for
   both stages is separately covered by 226 pre-existing unit tests
   (110 risk_engine + 116 compliance_engine).

7. **Only 2 of the profile's pairs (EURUSD, GBPUSD) were pushed through a
   full warmup + fail-closed cycle** in this sandbox session, constrained
   by the test's time budget. The remaining configured pairs were
   correctly skipped throughout (proving fail-closed behavior for them),
   but were not individually exercised through a full accept/warmup path.
