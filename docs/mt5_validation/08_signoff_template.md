# 08 — Final Phase 1 Sign-Off Template

**Status: DEPRECATED.** Written for `mt5/PhantomBridgeEA.mq5` (ADR-023's
original HTTP-only-transport EA), which no longer exists in this
repository -- it was replaced by `mt5/TitanProtocolEA.mq5` (socket
transport by default, with automatic HTTP fallback; ADR-034). See
`deployment_windows/REAL_MT5_VALIDATION_CHECKLIST.md` for the current
real-MT5 validation checklist. Kept for historical reference only.


Fill this in only from actual results observed on a real MetaEditor +
MT5 demo/live environment. Do not fill in any field from inference,
memory of a prior audit, or expectation of what "should" happen — every
line must trace to an observed compile log line or an observed test
result. Leave a field marked `REQUIRES REAL MT5 VALIDATION` rather than
guessing.

---

**Deployment/test identity**

- Date of validation run: ______________________
- Operator name: ______________________
- Git commit hash validated: ______________________
- MetaEditor build number: ______________________
- MT5 terminal build number: ______________________
- Broker / demo server used: ______________________

---

## 1. MetaEditor compile

- [ ] Compiled with **0 errors**
- [ ] Warning count: _____ (list each if nonzero)
- Compiler summary line (verbatim): ______________________
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION (not yet run)

## 2. `.ex5` generated

- File path: ______________________
- File size: ______________________
- Timestamp: ______________________
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 3. MT5 demo validation — functional/lifecycle (§A, 12 tests)

| Test | Result | Notes |
|---|---|---|
| A1 EA loads | ☐Pass ☐Fail ☐Not run | |
| A2 Symbol rejected | ☐Pass ☐Fail ☐Not run | |
| A3 Empty API key rejected | ☐Pass ☐Fail ☐Not run | |
| A4 OnTick | ☐Pass ☐Fail ☐Not run | |
| A5 OnTimer cadence | ☐Pass ☐Fail ☐Not run | |
| A6 OnTradeTransaction | ☐Pass ☐Fail ☐Not run | |
| A7 Heartbeat | ☐Pass ☐Fail ☐Not run | |
| A8 API authentication | ☐Pass ☐Fail ☐Not run | |
| A9 Secure communication | ☐Pass ☐Fail ☐Not run | |
| A10 Connection recovery | ☐Pass ☐Fail ☐Not run | |
| A11 Fail-closed timeout | ☐Pass ☐Fail ☐Not run | |
| A12 Emergency stop | ☐Pass ☐Fail ☐Not run | |

## 4. All commands verified (§B, 6 tests)

| Test | Result | Broker ticket(s) | Notes |
|---|---|---|---|
| T1 BUY | ☐Pass ☐Fail ☐Not run | | |
| T2 SELL | ☐Pass ☐Fail ☐Not run | | |
| T3 MODIFY_SL | ☐Pass ☐Fail ☐Not run | | |
| T4 MODIFY_TP | ☐Pass ☐Fail ☐Not run | | |
| T5 CLOSE | ☐Pass ☐Fail ☐Not run | | |
| T6 PARTIAL_CLOSE | ☐Pass ☐Fail ☐Not run | | |

## 5. Negative / adversarial tests (§C, 13 tests)

| Test | Result | Notes |
|---|---|---|
| N1 Invalid API key | ☐Pass ☐Fail ☐Not run | |
| N2 Invalid JSON | ☐Pass ☐Fail ☐Not run | |
| N3 Invalid symbol | ☐Pass ☐Fail ☐Not run | |
| N4 Invalid volume | ☐Pass ☐Fail ☐Not run | |
| N5 Market closed | ☐Pass ☐Fail ☐Not run | |
| N6 Duplicate execution_id | ☐Pass ☐Fail ☐Not run | |
| N7 Lost bridge connection | ☐Pass ☐Fail ☐Not run | |
| N8 Heartbeat timeout | ☐Pass ☐Fail ☐Not run | |
| N9 Broker rejection | ☐Pass ☐Fail ☐Not run | |
| N10 Trade context busy | ☐Pass ☐Fail ☐Not run | |
| N11 Requote | ☐Pass ☐Fail ☐Not run (real requote hard to force — see 02 test N11) | |
| N12 Partial fill | ☐Pass ☐Fail ☐Not run (broker/demo-dependent — see 02 test N12) | |
| N13 Network interruption | ☐Pass ☐Fail ☐Not run | |

## 6. Security verified

- [ ] API key required and enforced on every route (N1)
- [ ] Wrong/missing key never mutates server state
- [ ] Magic-number isolation confirmed against a foreign-magic position
- [ ] Transport topology documented (loopback vs. cross-host — A9)
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 7. Fail-closed verified

- [ ] A11 passed
- [ ] N7/N8/N13 passed (or documented if not exercisable)
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 8. Logging verified

- [ ] Every executed command has a matching log entry in
      `phantom/bridge/logging_sink.py`'s stream
- [ ] No unhandled exception traces observed during the full session
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 9. Emergency stop verified

- [ ] Server-side flag path (A12) passed
- [ ] EA-local `EmergencyDisable` path (A12) passed
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 10. Heartbeat verified

- [ ] A5 and A7 passed
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 11. Communication verified

- [ ] A8, A9, N2 passed
- [ ] `WebRequest` allow-list configured and confirmed necessary/
      sufficient (Step 3 of `03_execution_checklist.md`)
- **Status:** ☐ Pass ☐ Fail ☐ REQUIRES REAL MT5 VALIDATION

## 12. Bugs found during this validation run

List any defect discovered during actual compile/demo execution here
(not from static review — those are already captured in
`PHANTOM_BRIDGE_EA_PHASE1_VERIFICATION_AUDIT.md` and
`PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md`). For each: what broke, exact
repro steps, and whether it was fixed under the "only fix what compile/
demo discovers" rule.

1. ______________________
2. ______________________

## 13. Final recommendation

☐ **Approve Phase 1** — all safety-critical gates (§3 A11/A12, §5 N6,
security, fail-closed, emergency stop, logging) passed; all six trade
commands verified; any untestable negative case is explicitly
documented, not silently assumed passing.

☐ **Reject Phase 1** — list every blocking finding:
   - ______________________

☐ **Gate incomplete** — this package has not yet been run to
completion against a real MetaEditor/MT5 environment; no approve/
reject decision can be made from this template alone.

Signed: ______________________  Date: ______________________
