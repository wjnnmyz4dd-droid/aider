# PhantomBridgeEA Phase 1 — MetaTrader 5 Validation Package

Status of this package: **documentation only.** No code was modified to
produce it. Its purpose is to make Phase 1 independently verifiable on
a real Windows + MetaEditor + MT5 installation — something this
sandbox does not have (checked: no MetaEditor, no MT5 terminal, no
Wine, no Windows runtime of any kind are present here).

## Why this exists

Phase 1's own verification audit
(`PHANTOM_BRIDGE_EA_PHASE1_VERIFICATION_AUDIT.md`) and the subsequent
fix round (`PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md`) both concluded
with the same gap: everything verifiable by static inspection and by
the Python test suite (1714/1714 passing) has been checked, but a real
MetaEditor compile and a real MT5 demo execution have never happened,
because no environment capable of running either is available in this
project's sandbox. This package is the complete, self-contained
procedure an operator with that environment needs to close that gap —
without this session fabricating a result it cannot produce.

## What this package does NOT do

- It does not compile the EA.
- It does not run a demo test.
- It does not approve or reject Phase 1 — that decision belongs to
  whoever executes the package against a real environment and fills in
  `08_signoff_template.md`.
- It does not add any feature, and it does not touch Scanner, Evidence
  Engine, Strategy Engine, Statistical Risk Engine, Market Intelligence
  Engine, FTMO Compliance Engine, Research & Learning Engine, Watchdog,
  or Validation. Phase 1 remains scoped to exactly the transport/
  execution bridge it has always been.
- It does not authorize starting Phase 2. Per the original Phase 1
  instruction, Phase 2+ work begins only on explicit approval, and
  that approval can only follow a completed, real sign-off — which
  this package enables but cannot itself produce.

## Package contents

| File | Deliverable item |
|---|---|
| `docs/mt5_validation/01_metaeditor_compile_checklist.md` | Build configuration, compiler version, zero-errors/warnings gate, expected `.ex5` output, required includes/libraries, expected artifacts |
| `docs/mt5_validation/02_demo_validation_plan.md` | 12 functional/lifecycle tests, 6 trade-command tests, 13 negative/adversarial tests — each with purpose, steps, expected result, pass/fail criteria, recovery behavior |
| `docs/mt5_validation/03_execution_checklist.md` | Step-by-step operator sequence tying 01, 02, and 08 together in order |
| `docs/mt5_validation/04_deployment_checklist.md` | Pre-deployment, deployment, and first-24-hours checklist for moving from demo to a funded/eval account |
| `docs/mt5_validation/05_rollback_checklist.md` | Immediate-stop and full-rollback procedures |
| `docs/mt5_validation/06_troubleshooting_guide.md` | Symptom -> cause -> where-to-look, specific to this codebase, plus a documented list of known non-defect limitations |
| `docs/mt5_validation/07_production_readiness_checklist.md` | The gate between "passed demo validation" and "fit for a funded account" |
| `docs/mt5_validation/08_signoff_template.md` | The literal form to fill in from real results: MetaEditor compile, `.ex5` generated, MT5 demo validation, all commands verified, security verified, fail-closed verified, logging verified, emergency stop verified, heartbeat verified, communication verified, final recommendation |

## How to use this package

Start at `docs/mt5_validation/03_execution_checklist.md` — it is the
master sequence and references every other file in the right order.
`01`, `02`, `04`–`07` are procedures; `08` is the record. Nothing in
`01`–`07` should be marked complete from anything other than an actual
observed result on real MetaEditor/MT5.

## Rules this package was built under (restated for whoever executes it)

- Do not fabricate compile results.
- Do not fabricate MT5 demo results.
- Mark every item that requires real MT5 validation as such — never
  silently assume a pass.
- Do not change `mt5/PhantomBridgeEA.mq5` or any other code unless an
  actual compile run or an actual demo test discovers a defect, and
  even then, fix only what was discovered — nothing else.
- Stop after producing/executing this package. No Phase 2 work begins
  without an explicit, separate approval following a completed
  sign-off.
