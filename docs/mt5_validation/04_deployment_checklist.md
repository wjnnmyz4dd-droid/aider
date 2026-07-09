# 04 — Deployment Checklist

Applies once `03_execution_checklist.md` has passed on a demo account
and a decision has been made to move to a funded/prop-firm evaluation
account. This checklist does not itself authorize that decision — it
assumes it has already been made outside this package.

## Pre-deployment

- [ ] Confirm the sign-off in `08_signoff_template.md` recommends
      approval, with no unresolved blocking finding.
- [ ] Confirm the target account's broker permits EAs and
      `WebRequest` (some prop-firm accounts restrict either).
- [ ] Confirm `MagicNumber` on both the EA input and
      `BridgeConfig.magic_number` is unique to this deployment — never
      reused from a demo/test session against a live account, to avoid
      the bridge mistaking test-session positions for live ones.
- [ ] Confirm `ApiKey` is a freshly generated secret for this
      deployment, not the demo-testing key, and is stored only in the
      `.set` file / environment config, never committed to the
      repository.
- [ ] Confirm `AllowedSymbolsCsv` is scoped to exactly the symbols this
      deployment is meant to trade — an empty value defaulting to
      "current chart symbol only" is fine for a single-symbol chart,
      but must be set explicitly for a multi-symbol deployment.
- [ ] Review `MaxSlippagePoints`, `FailClosedTimeoutSeconds`,
      `MaxRetries`/`RetryDelayMs`, `MaxRequoteRetries`/
      `RequoteRetryDelayMs` against the target broker's real
      characteristics (spread, execution speed, requote frequency) —
      the Phase-1 defaults were chosen for correctness during
      development, not tuned against any specific broker.
- [ ] Confirm `BackendUrl` points at the correct bridge server instance
      for this account (never point a live account's EA at a bridge
      server also serving a demo/test account).

## Deployment steps

- [ ] Copy the exact `.ex5` compiled and validated in
      `01_metaeditor_compile_checklist.md` / `03_execution_checklist.md`
      — never a locally recompiled copy that hasn't been through this
      same validation, and never a copy with uncommitted local edits.
- [ ] Deploy the bridge server as a persistent process (service,
      supervisor, or equivalent) rather than an interactive terminal
      session that dies when the operator logs out.
- [ ] Attach the EA to the live/eval account's chart with production
      inputs (see pre-deployment list above).
- [ ] Re-run `02_demo_validation_plan.md` A1 (EA loads), A7
      (heartbeat), A8 (API auth), and A11/A12 (fail-closed, emergency
      stop) against the real account before any trade command is ever
      submitted to it — these are the safety gates and must be
      re-confirmed in the actual deployment target, not assumed to
      carry over from the demo run.
- [ ] Confirm monitoring/alerting is watching the bridge server's logs
      and metrics from the moment of deployment, not added later.

## Post-deployment (first 24 hours)

- [ ] Confirm at least one full BUY/SELL/CLOSE cycle executes correctly
      on the live/eval account with real (small) size before scaling up.
- [ ] Confirm the fail-closed and emergency-stop paths have a known,
      tested operator procedure (who gets paged, what they do) — not
      merely that the code behaves correctly in isolation.
- [ ] Confirm `.set` file, API key, and magic number used in production
      are recorded somewhere durable (not only in the operator's head)
      for the rollback checklist.
