# 07 — Production Readiness Checklist

**Status: DEPRECATED.** Written for `mt5/PhantomBridgeEA.mq5` (ADR-023's
original HTTP-only-transport EA), which no longer exists in this
repository -- it was replaced by `mt5/TitanProtocolEA.mq5` (socket
transport by default, with automatic HTTP fallback; ADR-034). See
`deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md` for the current
real-MT5 validation checklist. Kept for historical reference only.


This is the gate between "Phase 1 passed its demo validation" and
"Phase 1 is fit to run against a funded/prop-firm account." It assumes
`03_execution_checklist.md` is fully complete and
`08_signoff_template.md` recommends approval.

## Compile & artifact integrity

- [ ] `.ex5` compiled with 0 errors, reviewed warnings, from the exact
      source in this repository at a known commit hash.
- [ ] `.ex5` file hash/timestamp recorded and matched against what is
      actually attached to the production chart (no silent drift
      between "the one we tested" and "the one running").

## Functional coverage

- [ ] All of `02_demo_validation_plan.md` §A (lifecycle) passed.
- [ ] All of §B (BUY/SELL/MODIFY_SL/MODIFY_TP/CLOSE/PARTIAL_CLOSE)
      passed.
- [ ] All of §C (negative/adversarial) either passed or was explicitly
      documented as untestable-in-this-environment with a reason — no
      silent skips.

## Safety-critical gates (must all be a hard pass, no exceptions)

- [ ] Fail-closed timeout (A11) verified: zero commands execute while
      contact is lost past `FailClosedTimeoutSeconds`.
- [ ] Emergency stop (A12) verified via both the server-side flag and
      the EA-local `EmergencyDisable` input, independently.
- [ ] Duplicate/idempotency guarantee (N6) verified: no double
      execution, no double-reporting, under both duplicate submission
      and duplicate report resend.
- [ ] Magic-number isolation verified: the EA only ever reports/
      modifies positions carrying its own `MagicNumber` (re-confirm
      `SelectOwnedPosition`'s ownership check against a manually
      opened position with a different or no magic number present on
      the same account during testing).
- [ ] Pre-flight checks (Fix #3) verified against the real target
      broker's actual `SYMBOL_TRADE_MODE`/`SYMBOL_VOLUME_STEP`/
      `SYMBOL_TRADE_STOPS_LEVEL` values — these vary by broker and
      symbol and were only checked against whatever demo broker Step 6
      used.
- [ ] Requote handling (Fix #4 / N11) verified against at least one
      real requote, or explicitly documented as not exercised if the
      demo environment could not produce one — do not sign off "pass"
      on a test that never actually ran.

## Operational readiness

- [ ] Bridge server deployed as a persistent, monitored process (not
      an interactive session).
- [ ] Structured logs (`phantom/bridge/logging_sink.py`) are being
      collected somewhere durable, not just printed to a terminal that
      gets closed.
- [ ] `BridgeMetrics` counters are wired into whatever monitoring the
      operator actually watches (or a documented plan exists to add
      this before or shortly after go-live).
- [ ] An operator knows, in advance, exactly how to trigger the
      emergency stop (`05_rollback_checklist.md`'s immediate-stop
      section) without needing to read code first.
- [ ] Credentials (`ApiKey`) are unique to this deployment, not reused
      from testing, and stored outside version control.

## Documentation

- [ ] `PHANTOM_BRIDGE_EA_PHASE1_REPORT.md`,
      `PHANTOM_BRIDGE_EA_PHASE1_VERIFICATION_AUDIT.md`, and
      `PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md` are all consistent with
      the version actually being deployed (no undocumented drift since
      the fix report).
- [ ] This validation package's sign-off
      (`08_signoff_template.md`) is filled in and attached to whatever
      change-management record this organization uses for production
      trading changes.

## Explicit non-goals (do not block sign-off on these — they are
future phases, not Phase 1's scope)

- Scanner, Strategy Engine, Statistical Risk Engine, Market
  Intelligence Engine, FTMO Compliance Engine, Research & Learning
  Engine, Watchdog, and Validation are all out of scope for this gate.
  Phase 1 is the execution/transport bridge only; it has no opinion on
  whether a given trade *should* be taken, only on executing exactly
  the command it was given, safely and idempotently.
