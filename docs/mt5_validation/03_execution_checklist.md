# 03 — Complete Execution Checklist (Operator Step-by-Step)

**Status: DEPRECATED.** Written for `mt5/PhantomBridgeEA.mq5` (ADR-023's
original HTTP-only-transport EA), which no longer exists in this
repository -- it was replaced by `mt5/TitanProtocolEA.mq5` (socket
transport by default, with automatic HTTP fallback; ADR-034). See
`deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md` for the current
real-MT5 validation checklist. Kept for historical reference only.


Follow this in order. Each step references the detailed procedure it
draws from. Do not skip ahead — later steps assume earlier ones passed.

## Step 0 — Environment preparation

- [ ] Windows machine (physical or VM) with MetaEditor + MT5 terminal
      installed, matching a broker that offers a demo account.
- [ ] Python 3.9+ available to run the bridge server
      (`phantom/bridge/server.py`) on the same machine or one reachable
      from the terminal.
- [ ] This repository checked out at the commit that includes
      `PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md` (the fixed EA) or later.
- [ ] Demo account credentials in hand; logged into the terminal.

## Step 1 — Compile

- [ ] Work through `01_metaeditor_compile_checklist.md` in full.
- [ ] **Gate:** if compile errors exist, fix only those errors (per
      the rule: no feature work, no other file touched), recompile,
      and repeat until 0 errors. Do not proceed to Step 2 with any
      compile error outstanding.
- [ ] Record the compiler result in `08_signoff_template.md` §1.

## Step 2 — Stand up the bridge server

- [ ] Start `phantom/bridge/server.py`'s `serve(...)` with a
      `BridgeConfig` matching the EA's `.set` inputs (same `api_key`,
      `magic_number`, `allowed_symbols`).
- [ ] Confirm all 9 routes respond (a quick `curl` against
      `/bridge/heartbeat` with the correct key/magic number should
      return `200 {"status": "ok", ...}`).
- [ ] Confirm the port matches `BackendUrl` in `PhantomBridgeEA.set`.

## Step 3 — Configure MT5 for outbound requests

- [ ] **Tools -> Options -> Expert Advisors -> Allow WebRequest for
      listed URL** -> add the exact `BackendUrl` value (including
      port). `WebRequest` silently fails with a negative/zero status
      if this is not set — this is the single most common false
      "connection lost" symptom in Step 5.
- [ ] Enable **Allow algorithmic trading** globally (toolbar toggle)
      and per-EA (Common tab checkbox on attach).

## Step 4 — Attach the EA

- [ ] Drag `PhantomBridgeEA.ex5` onto a chart for an allowed symbol.
- [ ] Set inputs from `PhantomBridgeEA.set` (or load the `.set` file
      directly via the Inputs tab's "Load" button), with a real
      `ApiKey` matching the bridge server's configured key.
- [ ] Confirm Step in `02_demo_validation_plan.md` A1 passes
      (smiley face, Journal init message).

## Step 5 — Functional/lifecycle tests

- [ ] Run `02_demo_validation_plan.md` tests A1 through A12 in order.
- [ ] Record each result (pass/fail + notes) in
      `08_signoff_template.md`.
- [ ] **Gate:** if any of A1–A3 (init) or A11–A12 (fail-closed,
      emergency stop) fail, stop — these are safety-critical and
      must not be waived. A4–A10 failures should also block sign-off
      unless independently triaged and explicitly accepted with a
      documented reason.

## Step 6 — Trade command tests

- [ ] Prepare a way to submit `TradeCommand`s into the running
      `BridgeEngine` (a small script calling `engine.submit_command`
      directly, or an interactive Python session against the same
      process — Phase 1 does not expose command submission as its own
      HTTP route).
- [ ] Run `02_demo_validation_plan.md` tests T1 through T6 in order,
      each against a fresh position where applicable.
- [ ] Record each result in the sign-off template.
- [ ] **Gate:** all six must pass before proceeding — a broken trade
      command is a hard blocker for Phase 1 approval.

## Step 7 — Negative / adversarial tests

- [ ] Run `02_demo_validation_plan.md` tests N1 through N13.
- [ ] Some (N11 requote, N12 partial fill) depend on real market/
      broker conditions that cannot be forced on demand — if the demo
      environment cannot produce them, document that explicitly rather
      than marking pass/fail. Do not claim a pass without an actual
      observed requote/partial fill.
- [ ] Record each result in the sign-off template, including any test
      that could not be exercised and why.

## Step 8 — Log and metric review

- [ ] Review the bridge server's structured logs
      (`phantom/bridge/logging_sink.py` event stream) end-to-end for
      the session: confirm every command has a matching execution
      report, every heartbeat is logged, and no unexpected exception
      traces appear.
- [ ] Review `BridgeMetrics` counters for the session and sanity-check
      them against the tests actually run (e.g. commands executed
      count should match Step 6/7's actual command count).

## Step 9 — Sign-off

- [ ] Complete `08_signoff_template.md` in full, including the
      explicit "requires real MT5 validation" markers for anything not
      actually exercised.
- [ ] Route the completed sign-off back for the approve/reject
      decision this package itself cannot make (see the package index
      for why).

## Step 10 — Only if this is a genuine deployment (not just a test run)

- [ ] Continue into `04_deployment_checklist.md`.
