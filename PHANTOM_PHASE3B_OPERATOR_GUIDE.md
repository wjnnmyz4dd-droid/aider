# Phantom Phase 3B — Operator Guide (System Reliability)

This guide covers day-to-day operation of the System Reliability Engine
(`phantom/reliability/`, ADR-032) alongside the Runtime Orchestrator
(`phantom/runtime/`, ADR-031). It assumes the reader already knows how
to start/stop the Runtime pipeline itself (see `PHANTOM_RUNTIME_
ORCHESTRATOR_PHASE3A_REPORT.md` and the Phase 5 deployment guides for
that).

## 1. What the Reliability Engine is, in one sentence

A read-only observer that watches heartbeats, cycle outcomes, resource
usage, and queue depth, and answers one question — **"is it currently
safe to keep trading?"** — without ever deciding a trade itself or
reaching into Runtime to change anything.

## 2. Wiring it in

```python
from phantom.reliability import ReliabilityEngine, ReliabilityConfig

reliability = ReliabilityEngine(ReliabilityConfig())

# Once per pipeline tick, after Runtime finishes a cycle:
cycle_report = orchestrator.run_cycle(pairs, profile, inputs, now, cycle_id)
reliability.record_cycle(cycle_report)

# Periodically (e.g. once per engine's own health-check tick):
reliability.report_heartbeat("evidence_engine", now)
reliability.report_heartbeat("market_intelligence", now)
reliability.report_heartbeat("strategy_engine", now)
reliability.report_heartbeat("risk_engine", now)
reliability.report_resource_usage(now)
reliability.report_queue_depth("bridge_commands", queue.depth(), now)

# Whenever you need the current verdict:
health = reliability.evaluate_health(now)
```

`ReliabilityEngine` is thread-safe — one instance can be shared across
every pair's cycle-processing thread.

## 3. Reading a `SystemHealthSnapshot`

| Field | Meaning |
|---|---|
| `degradation_level` | `NORMAL` / `DEGRADED` / `CRITICAL` / `HALTED` — the headline verdict |
| `component_health` | Per-engine `HEALTHY`/`DEGRADED`/`UNHEALTHY`/`UNKNOWN`, derived from heartbeat age |
| `resource_usage` | Latest CPU%/memory% sample (either may be `None` if that one sampler failed — this is not itself a fault, just missing data) |
| `queue_depths` | Latest reported depth per named queue |
| `cycle_stats` | Per-pair total/failed cycle counts, average duration, last outcome |
| `reasons` | Human-readable list of everything that contributed to the current `degradation_level` |

## 4. What to do at each degradation level

- **NORMAL** — no action needed.
- **DEGRADED** — at least one signal (a moderately stale heartbeat,
  elevated CPU/memory, a growing queue, or a rising per-pair failure
  rate) is worth watching. Trading can continue; increase monitoring
  frequency.
- **CRITICAL** — a component is unhealthy, a resource is at a critical
  threshold, a queue is critically backed up, or a pair's rolling
  failure rate has crossed the configured critical threshold. Consider
  pausing new trade cycles for the affected pair(s) until the signal
  clears; this is an operator/automation decision — Reliability does
  not make it for you.
- **HALTED** — at least one restartable engine has gone completely
  silent (no heartbeat ever recorded, or its heartbeat exceeded the
  configured grace period) or produced a future/inverted timestamp
  (never trusted). **Stop feeding new cycles** until the component's
  heartbeat resumes. This is the one level with an unambiguous,
  fail-closed recommendation.

## 5. Recovery: what `attempt_recovery()` will and won't do

```python
outcome = reliability.attempt_recovery("evidence_engine", now)
# outcome.attempted, outcome.succeeded, outcome.reason
```

Only these four components can ever be restarted through this engine:
`evidence_engine`, `market_intelligence`, `strategy_engine`,
`risk_engine` (the same allow-list ADR-031's Watchdog integration
already defines — reused, not redefined). Calling `attempt_recovery()`
for `bridge`, `compliance_engine`, or `"runtime"` itself always returns
`attempted=False` — this is by design, not a bug: those three
components' correctness is too safety-critical to auto-restart from
this engine.

## 6. Snapshot freshness

```python
reliability.is_snapshot_fresh(evidence_snapshot.generated_at, now)
```

A `False` result means the evidence backing a Runtime decision is
older than `ReliabilityConfig.snapshot_freshness_threshold_seconds`.
This is advisory, not a gate Runtime itself checks — an operator or
automation layer decides what to do with a stale-snapshot warning
(e.g. don't act on that pair's last decision, re-request fresh data).

## 7. Trading Profile selection

Six built-in profiles cover the common cases (see `phantom/runtime/
profiles.py` and §8 of the Release Readiness report for full
per-profile detail):

- `london_conservative` / `london_aggressive` — London session only.
- `new_york_conservative` / `new_york_aggressive` — New York session
  only.
- `london_and_new_york` — both sessions, engine-default risk.
- `custom` — build your own via `make_custom_profile(...)`, but run it
  through `phantom.runtime.validation.validate_profile()` before
  deploying it; a corrupted or ineligible custom profile is rejected
  deterministically, never silently coerced.

"Conservative" vs. "aggressive" differ only in `risk_profile` (tighter
daily/portfolio risk limits and fewer max open positions) — sessions,
pairs, strategies, compliance profile, and news policy are otherwise
identical within the same city pairing.

## 8. Daily protection curves, at a glance

Three independent graduated curves, all driven by the account's own
`AccountState` (no hidden state, no persistent penalty):

- **Daily Loss** — resets every trading day against that day's own
  `daily_starting_balance`. Reducing position size progressively as
  more of the day's loss limit is consumed; the top band hard-rejects
  all new positions regardless of setup quality.
- **Total Drawdown** — measured against `peak_balance`, which the daily
  reset never touches — a bad day's drawdown consumption carries over
  until equity actually recovers toward the peak.
- **Daily Profit Protection** — optionally reduces size (and can
  optionally hard-stop) once the day's profit crosses configured
  thresholds, to protect gains rather than let a good day's edge give
  it all back.

All three are pure functions of the current account state — there is
no "sticky" penalty that persists once the underlying numbers recover.

## 9. Known limitations to keep in mind operationally

See §10 of `PHANTOM_PHASE3B_RELEASE_READINESS_REPORT.md` for the full
list. The two most operationally relevant:

- **News feed trust is a single on/off switch**, not per-provider. If
  you integrate a second news feed in the future, today's engine has
  no way to detect disagreement between two feeds or fail over from
  one to the other — you would be responsible for reconciling feeds
  before calling `evaluate()`.
- **The audit record doesn't capture everything an operator might want
  during an incident review** — no Market Intelligence summary, and
  Risk/Bridge decisions are collapsed to a bool/error-code. For deep
  forensic replay, retain the original `EvidenceSnapshot`/
  `MarketIntelligenceSnapshot`/`RiskSnapshot`/`ComplianceSnapshot`
  objects yourself alongside the audit record, rather than relying on
  the audit record alone.

## 10. Quick troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| `degradation_level == HALTED` immediately after startup | No heartbeat has been reported yet for one or more engines | Confirm your supervisor loop calls `report_heartbeat()` for all 4 restartable engines before the first `evaluate_health()` call |
| `resource_usage.cpu_percent is None` | The default stdlib sampler (`os.getloadavg()`) isn't supported on this platform (e.g. Windows) | Supply a platform-appropriate `cpu_sampler`/`memory_sampler` callable to `ReliabilityEngine.__init__` |
| A pair stays `CRITICAL` after fixing the underlying issue | The failure-rate window hasn't rolled over yet | Keep recording successful cycles — the rolling window (`cycle_history_window`, default 100) needs enough recent successes to push old failures out |
| `attempt_recovery("bridge", ...)` always refused | This is by design | Restart the Bridge process through your own infrastructure tooling, not through this engine |
