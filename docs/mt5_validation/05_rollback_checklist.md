# 05 — Rollback Checklist

Use when a deployed `PhantomBridgeEA` needs to be pulled back — a
defect surfaces in production, a fix needs to be tested, or the
operator simply needs to stop trading immediately.

## Immediate stop (seconds, no code/config change needed)

- [ ] Call `POST /bridge/emergency-stop {"active": true}` against the
      running bridge server. This halts new command issuance
      immediately and is picked up by the EA on its very next poll
      (`emergency_stop: true`, empty command list) — no EA restart
      required. This is the fastest available stop and should be the
      first action in any incident.
- [ ] Alternatively/additionally, toggle **AutoTrading** off in the
      MT5 toolbar — this stops the EA from executing anything
      terminal-wide, independent of the bridge server's state.
- [ ] Confirm no further `ReportExecutionResult` calls occur after the
      stop (watch the bridge server logs for ~1 minute).

## Full rollback (remove the EA / revert to a known-good state)

- [ ] Detach the EA from the chart (right-click chart -> Expert
      Advisors -> Remove), or set `EmergencyDisable=true` on its
      inputs and reattach if immediate removal isn't possible.
- [ ] Stop the bridge server process.
- [ ] Confirm the account's open positions/pending orders are in a
      known, intentional state — do not assume the rollback itself
      should close positions; that is a separate trading decision, not
      an automatic side effect of stopping the bridge.
- [ ] If rolling back to a prior `.ex5`/`.set` version: restore the
      exact prior compiled artifact and its matching `.set` file from
      version control / backup, not a freshly recompiled copy of an
      older commit (recompiling can pick up a different MetaEditor/
      terminal build's behavior — re-run
      `01_metaeditor_compile_checklist.md` against the restored source
      if a fresh compile is unavoidable).
- [ ] If rolling back the Python bridge server: restore the exact
      prior `phantom/bridge/` commit and redeploy; do not mix a rolled-
      back EA with a newer/older bridge server without re-validating
      the pair together (message-shape/`SCHEMA_VERSION` compatibility
      is not guaranteed across arbitrary version combinations).

## After rollback

- [ ] Record what triggered the rollback, the exact stop time, and the
      account state at that time (open positions, last executed
      command's `correlation_id`) before doing anything else — this is
      the incident record a fix will need.
- [ ] Do not redeploy until the triggering defect has gone through
      `01`–`03` again against the fixed version.
- [ ] Confirm the rollback itself didn't leave the bridge server and
      EA pointed at mismatched versions or configs (a stale `.set`
      file with an old `ApiKey` is a common rollback mistake).
