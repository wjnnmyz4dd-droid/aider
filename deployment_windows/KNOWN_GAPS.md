# Titan Protocol Windows Deployment — Known Gaps

This deployment layer wires together every real, existing, public
interface in `titan_protocol/` (Bridge, the 5 core trading engines,
Runtime Orchestrator, Reliability, market-data ingestion, news
ingestion) exactly as documented in `PHANTOM_MT5_DEPLOYMENT_AUDIT.md`
(historical) and the ADRs referenced below. It adds **zero new trading
logic, zero engine modifications, and zero architectural redesign.**
Both gaps originally recorded here are now CLOSED in code; one residual
*configuration* limitation remains (section 2) and one residual
*environmental* limitation applies to both (running status requires a
real, connected MT5 EA — see section 1). Recorded here rather than
papered over.

## 1. Live market-data ingestion — CLOSED, Amendment 1 (ADR-023)

**Closed by:** `start.py`'s `_live_cycle_loop()`, fed by
`titan_protocol/market_data_ingestion/` (ADR-033 Part 1). The EA reports
bars/ticks to the Bridge's `POST /bridge/market-data` endpoint
(`titan_protocol/bridge/server.py`'s `_handle_market_data`); once
`MarketDataIngestionEngine.is_ready(pair, timeframe, now)` says a pair's
feed is warmed-up and fresh, `_live_cycle_loop()` pulls its real
bars/spread via `get_bars()`/`latest_spread()` and calls
`RuntimeOrchestrator.run_cycle()` with them — never with fabricated
data. A pair with no data yet is simply skipped for that tick (see
`state/health.json`'s `live_cycle` field and `health_check.py`'s
"market-data readiness" check, which reports real
warmup/fresh/accepted/rejected/gap/tick counts, not a static
placeholder).

**Residual limitation:** this closes the *code* gap, not the
*environment* one — the feed only becomes ready once a real MT5
terminal is running `TitanProtocolEA` and actually reporting bars.
Without a real MT5 EA connected (e.g. in an environment with no MT5
terminal at all), `is_ready()` never returns true for any pair, the
live-cycle loop skips every tick, and overall status stays **DEGRADED**
— this is the live-cycle loop correctly reporting "no real data yet,"
not a bug. Persisted day-start/peak-balance/lock tracking across
restarts (`titan_protocol.compliance_state_store`) is real and
independent of this gap; it does not by itself flip status to HEALTHY
either, since HEALTHY additionally requires a live, currently-connected
EA.

## 2. Multi-provider news system (Trading Economics / Forex Factory) — CLOSED, Phase 3E

**Closed by:** `titan_protocol/news_ingestion/` (ADR-033 Part 2, Phase 3E) —
a real Trading Economics primary / Forex Factory automatic-backup
failover engine, wired into `start.py`'s live-cycle loop and exposed
through `health_check.py`'s "news provider failover" check and
`state/health.json`'s `news` field. `MarketIntelligenceEngine` itself
is unmodified and still has exactly one seam (`news_feed_trusted` +
`events`) — it never knows which provider is active; this package only
supplies it better, failover-protected data through that same existing
seam. Never merges, averages, or votes between providers (verified by
`tests/titan_protocol/news_ingestion/test_failover.py`'s
`TestNoMergeAverageOrVote`).

**Residual limitation:** `forex_factory_base_url` defaults to empty in
the shipped example config — an operator must point it at a real JSON
calendar feed (shape documented in
`titan_protocol/news_ingestion/providers/forex_factory.py`'s own
docstring) for the backup provider to actually be reachable. Until
configured, a Trading Economics outage fails closed immediately (no
functioning backup), which is the same safe behavior as before this
phase, not a regression.

## 3. Live-cycle `PortfolioState` position adapter — CLOSED (count-based gating), residual approximations remain

`deployment_windows/start.py`'s live-cycle loop previously constructed
`PortfolioState()` with no arguments on every cycle, so
`portfolio_state.open_positions` was permanently empty regardless of what
the EA actually had open. `check_position_limits()` could therefore never
reject a duplicate entry for an already-open pair, and
`RuntimeOrchestrator` (which generates a fresh `TradeCommand`/
`correlation_id` every cycle whenever `compliance.ready_for_bridge` is
true, with no in-flight-command check of its own) would keep submitting
new commands for the same signal indefinitely.

Fixed: `_map_bridge_positions_to_open_positions()` now maps
`BridgeEngine.latest_positions` (real, EA-reported `PositionReport`s) into
`risk_engine.models.OpenPosition`, wired into the `PortfolioState` built
each cycle. This closes the specific defect (`check_position_limits()`
can now see and reject an already-open pair). Three approximations remain,
documented rather than silently assumed correct:

- **`OpenPosition.size_r` is fixed at `0.0`.** It represents risk
  allocated to the position *in R*, which cannot be derived from
  `PositionReport`'s volume/open_price/stop_loss without also knowing the
  account's risk-per-R at the time the position was opened -- the EA does
  not report this, and no existing module in this repo computes it from
  raw volume alone. Fabricating a value would inject an unverified number
  into `compute_exposure_summary()`/`check_safety_limits()`/
  `compute_correlation_status()` -- real capital-preservation gates --
  which would be worse than the previous gap, not better. Those three
  functions therefore remain blind to already-open positions' risk
  contribution; only count-based gating is fixed.
- **`OpenPosition.opened_at` uses the position's last `received_at`**
  (report time), not true open time -- drifts up to one report cycle
  (~5s). Not consumed by `check_position_limits()`.
- **"Positively reported zero positions" vs. "never reported" was
  structurally ambiguous** from `BridgeEngine.latest_positions` alone (both
  produce an empty tuple) -- **CLOSED**: `BridgeEngine.last_positions_received_at`
  (set unconditionally by `handle_positions()`, including on an empty
  snapshot) now gives a real, always-populated timestamp independent of
  `latest_positions` itself. `is_connection_healthy` (heartbeat freshness)
  remains the gate for whether to trust `latest_positions` for *this
  cycle's* trading decisions at all (no recent heartbeat -> every pair is
  skipped, `no_recent_position_report`, fail-closed) -- `
  last_positions_received_at` is used specifically to confirm a
  *just-resolved* command's pair before allowing a new submission (see
  section 4).

## 4. Pair-level in-flight command guard — CLOSED, including the resolution-vs-position race

A separate, related gap recorded above -- `RuntimeOrchestrator` had no
pair-level in-flight-command guard covering the window between command
delivery and the next valid position report, so it would submit a fresh
`TradeCommand` (with a new `correlation_id`, since it's
`f"{cycle_id}:{pair}"`) every cycle for as long as `compliance.
ready_for_bridge` stayed true -- is now closed by
`titan_protocol/runtime/in_flight_commands.py`'s `InFlightCommandRegistry`,
wired into `RuntimeOrchestrator` (optional constructor parameter,
`start.py`-constructed with a 300s TTL) and reconciled every live-cycle
tick against `BridgeEngine.command_resolved()`. See the in-flight
registry design note in the engineering log for the full root-cause
trace and architecture comparison.

**A regression traced after this closed:** an `ExecutionReport` can
arrive (resolving a command) before the *next* `/bridge/positions`
snapshot catches up to reflect the position it just opened -- these are
two independently-timed EA-reported events, not one atomic update.
Dropping a pair's in-flight entry the instant its command resolved left
a real window where a second command could be submitted while
`PortfolioState` still reflected the pre-execution count. **CLOSED**:
`InFlightCommandRegistry` now moves a resolved (not TTL-expired) pair
into a second, "awaiting position confirmation" state; only
`confirm_position_report(BridgeEngine.last_positions_received_at)` --
called every live cycle -- can release it, once that snapshot is
provably no older than the resolution itself. TTL-expired entries skip
this extra wait (no `ExecutionReport` ever arrived, so there is nothing
fresher to wait for). This never infers position truth from the
`ExecutionReport` itself -- that remains solely `BridgeEngine.
latest_positions`'s job.

**A production-readiness review found two further gaps in this same
mechanism, both now CLOSED (ADR-034 Amendments 8/9):**

1. **The "awaiting position confirmation" wait had no upper bound** -- if
   `/bridge/positions` reporting permanently stopped after a command
   resolved, the pair would stay blocked forever even though the
   underlying command was long since terminal. **CLOSED**:
   `InFlightCommandRegistry.expire_stale_position_confirmations()`
   releases the pair fail-safe once it has waited longer than the new,
   configurable `RuntimeConfig.position_confirmation_timeout_seconds`
   (default 120s), logging a clear warning and incrementing a cumulative
   counter (`position_confirmation_timeout_count()`, surfaced in
   `run_status`/`health_check.py`). `ComplianceEngine`'s own
   `max_positions_per_pair` check (fed by real `/bridge/positions`
   reports, independent of this registry) remains the actual
   duplicate-position guard once reporting resumes -- this timeout only
   prevents an unrecoverable deadlock in the registry itself.
2. **`CommandQueue`/`InFlightCommandRegistry` were purely in-memory** -- a
   Bridge process restart between "command delivered" and "reconciled"
   forgot the command existed until the next positions snapshot arrived,
   risking a duplicate submission for a pair whose prior command might
   still resolve into a real position. **CLOSED**: a new, lightweight
   `titan_protocol/runtime/in_flight_store.py` (same atomic-write
   technique as `compliance_state_store`) persists only the four minimal
   fields needed to recover the pair-level block -- correlation_id,
   pair, state, and its original timestamp, deliberately never the full
   `TradeCommand` -- and reloads them on startup, using their original
   timestamps so TTL/timeout windows keep counting from when they
   actually happened rather than resetting on every restart. **Accepted
   limitation, by design:** a command genuinely delivered before a
   restart whose `ExecutionReport` only arrives afterward cannot be
   recorded (the restarted `CommandQueue` never enqueued it, so
   `handle_execution_report()` correctly returns `False` for it) -- the
   pair stays protected by its own restart-surviving TTL until that
   elapses. Persisting the full `TradeCommand` to close this residual
   window was deliberately rejected as disproportionate, given
   `ComplianceEngine`'s independent live position-limit check already
   covers the actual duplicate-position outcome once positions reporting
   resumes post-restart. Corruption of the persisted file is handled
   fail-safe (an empty restore, never a crash), not fail-closed, since
   refusing to start the Bridge over a best-effort optimization file
   would itself be a worse capital-preservation outcome.

## 5. `compliance.max_positions_per_pair` defaulted to 2, not 1 — CLOSED

A second, independent regression found after section 4's fix shipped:
`ComplianceRuleProfile.max_positions_per_pair` (the field
`check_position_limits()` gates on) defaulted to **2**, not 1, in every
production code path -- the dataclass default and `config_loader.py`'s
unmodified `ComplianceEngineConfig()` both used it, and the JSON config
had no override path for this field at all. With exactly one open
position on a pair, `positions_for_pair(1) >= max_positions_per_pair(2)`
was false, so compliance approved a second entry -- correctly, per how
it was configured, but not per Titan's intended "never more than one
open position per pair" invariant. The in-flight guard (section 4) was
never the defect here; it worked exactly as designed for a genuinely new,
compliance-approved signal.

**CLOSED:**
- `ComplianceRuleProfile.max_positions_per_pair` default corrected to `1`
  (`titan_protocol/compliance_engine/models.py`).
- Now configurable via `compliance.max_positions_per_pair` in
  `titan_protocol_config.json` (`deployment_windows/config_loader.py`),
  defaulting to `1` when absent, and validated at startup: must be an
  integer >= 1, or startup fails closed with a `ConfigError` before any
  engine or thread starts.
- Dedicated logging: `compliance_engine.logging_sink.
  log_position_limit_check()` fires every cycle with `pair`,
  `positions_for_pair`, `max_positions_per_pair`, and whether it
  rejected; `log_compliance_snapshot()` now also includes the
  compliance decision's `reason`; the live-cycle loop's
  `portfolio_state_source` log now includes `position_report_age_seconds`.

Widening this value (e.g. `2`, for a deliberate scaling/pyramiding
strategy) remains fully supported -- it is a configuration choice, not a
hard-coded constant, and is proven by dedicated tests both at 1 and at 2.
`titan_protocol/risk_engine/config.py`'s own, independently-configured
`max_positions_per_pair` (used by `risk_engine/safety_limits.py` for its
own, separate portfolio-heat-driven gate) was deliberately left
untouched -- it is a different engine's different limit, not implicated
in this trace, and compliance's own gate is sufficient on its own to
enforce the invariant regardless of what value Risk Engine's copy holds.

## 6. Run Status diagnostics — CLOSED

No "Run tab" or dashboard exists anywhere in this deployment layer (this
is a Python trading engine with no browser surface) -- the closest
equivalent, `state/health.json` + `health_check.py`, previously scattered
the facts an operator needs to answer "why is Titan trading or not"
across several separate fields (`bridge_reachable`, `mt5_connected`,
`live_cycle`, `market_data`, `news`) or, for per-cycle decision
reasoning, nowhere at all -- `RuntimeOrchestrator.run_cycle()`'s return
value (`CycleReport`/`RuntimeAuditRecord`, carrying each pair's
`outcome`/`reasons`/`compliance_decision`/`bridge_correlation_id`) was
computed every cycle inside `_live_cycle_loop()` and immediately
discarded (`orchestrator.run_cycle(...)` with no assignment).

**CLOSED:** `state/health.json` gained a single `run_status` block, and
`health_check.py` gained a RUN STATUS panel printed at the end of its
output, covering: communication mode (HTTP/socket), HTTP fallback
enabled/disabled, Bridge connection status, overall runtime status, last
heartbeat age, last PositionReport age (via `BridgeEngine.
last_positions_received_at`, closing the same "empty snapshot has no
timestamp" gap section 3 already fixed), in-flight command count, open
positions per pair, the configured `max_positions_per_pair`, compliance
state (READY/BLOCKED) and block reason, the last submitted
`correlation_id`, and a per-pair cycle-outcome breakdown (merging
pre-engine skip reasons with `run_cycle()`'s own per-pair
`RuntimeAuditRecord`, now captured via `_LiveCycleStatus.
update_decisions()` instead of being discarded). Every field is read
from an object this process already holds a reference to -- no new
computation, only surfacing what already existed.

## 7. Transport default flip (socket → http) + EA HTTP-status classification fix — CLOSED

A live deployment's MT5 Experts log showed every `/bridge/heartbeat`,
`/bridge/account`, `/bridge/positions` request failing identically:
`WebRequest()` returning `1001`, `GetLastError()` `5203`, ~7000ms
elapsed, logged by the EA as `"rejected, HTTP 1001"`. A forensic trace
(read-only, no code changed until this fix) found two real, separate
defects:

**Defect A — invalid HTTP-status classification.** `HttpPost()`/
`HttpGet()` (`mt5/TitanProtocolEA.mq5`) treated any `WebRequest()`
return `> 0` as "a real HTTP response, just not success." `1001` is
outside the valid HTTP status range (100-599) and is not something this
Bridge could ever have sent (`server.py` only ever returns
200/400/401/404/500). This misclassification also skipped
`PrintWebRequestWhitelistGuidance()` (only called from the `status <= 0`
branch), so the `TITAN_DIAG BLOCKED` marker `diagnose_communication.py`
depends on for confidently telling "blocked before the Bridge" apart
from "the Bridge responded" was never emitted for this exact signature.

**CLOSED:** `HttpPost()`/`HttpGet()` now classify strictly: 100-599 is a
genuine HTTP response (unchanged), `<= 0` is a `WebRequest()`-layer
failure (unchanged, still `TITAN_DIAG BLOCKED`), and a positive value
outside 100-599 is now its own explicit, honestly-labeled
`PrintHttpTransportPseudoStatusFailure()` branch, emitting `TITAN_DIAG
NO_RESPONSE` (never worded "HTTP `<n>`" or "rejected"/"Bridge rejected").
`deployment_windows/diagnose_communication.py` now recognizes this exact
marker (`pseudoStatus=` field) and classifies it directly and
confidently as state 2, instead of falling through to its previously
uncertain default branch.

**Defect B (as a precaution, not proven by the trace alone) — shipped
transport default.** `BridgeConfig.transport` and the EA's `Transport`
input both defaulted to `"socket"` (ADR-034 Amendment 2). The forensic
trace could not rule out a socket-primary deployment's HTTP-fallback-
listener bind failing silently (logged only as a warning) as a
contributing factor.

**CLOSED (ADR-034 Amendment 4):** both defaults revert to `"http"`.
`"socket"` remains fully supported as an explicit opt-in
(`bridge.transport: "socket"` / `Transport=Socket`) — no code path,
message schema, or validation rule changes, only which value ships as
the out-of-the-box default. See
`docs/adr/ADR-034-mt5-bridge-transport-hardening.md` Amendment 4 for the
full rationale.

**Superseded (ADR-034 Amendment 7):** the operator's actual VPS, running
the Amendment 4-6 build, produced persistent (not intermittent)
`WebRequest()` `1001`/`GetLastError=5203` failures on every
`/bridge/heartbeat`/`/bridge/account` attempt, with elapsed time
consistently exceeding `WebRequest()`'s own 5000ms timeout parameter —
conclusive field evidence the HTTP/WinINet path is unreliable on this
deployment, not merely a hypothetical risk. Both defaults revert back to
`"socket"`/`TRANSPORT_SOCKET`; `"http"`/`TRANSPORT_HTTP` remain fully
supported as an explicit rollback. See
`docs/adr/ADR-034-mt5-bridge-transport-hardening.md` Amendment 7 —
including the operational note on why recompiling alone does not change
an already-attached EA's active transport, and the exact steps
(`verify_transport_configuration.py`) to confirm the switch actually took
effect on a live deployment.

## 8. `AccountState` had no freshness gate — CLOSED (ACCOUNT_STATE_STALE)

`BridgeEngine.latest_account_state` is set only when `/bridge/account`
succeeds and never expires — once set, it persists indefinitely.
`_build_compliance_account_state()` (`deployment_windows/start.py`) only
checked `if latest is None`, never how old `latest` was. If
`/bridge/account` succeeded exactly once and then kept failing (e.g.
during the WebRequest instability in section 7), compliance kept
evaluating daily-loss/drawdown/profit-protection against that one
frozen, increasingly stale balance indefinitely — real losses or gains
since that snapshot were invisible to the compliance gate, the opposite
failure mode of "not trading": the system could keep trading past a
real daily-loss threshold without knowing it.

**CLOSED:** `ComplianceEngine.evaluate()` now rejects with
`ACCOUNT_STATE_STALE` (an early gate, alongside
`EMERGENCY_STOP_ACTIVE`/`COMPLIANCE_LOCK_ACTIVE`) whenever
`AccountState.account_report_age_seconds` exceeds the configurable
`ComplianceRuleProfile.max_account_state_age_seconds` (default 30s,
matching the EA's own `FailClosedTimeoutSeconds`; configurable via
`compliance.max_account_state_age_seconds`, fails closed at startup for
any value <= 0). This fail-closed gate:
- blocks all new trade entries for the affected pair(s) until a fresh
  report arrives -- it does not merely skip the daily-loss/drawdown
  curves while still evaluating everything else;
- never affects existing position management -- `ComplianceEngine` has
  no position-close/modify authority at all (ADR-028 Hard Rule 1: only
  APPROVE/REDUCE/REJECT a proposed *new* entry);
- resumes automatically the moment a fresh `/bridge/account` report
  succeeds -- there is no separate "resume" mechanism to fail, since
  `evaluate()` is a pure function of its inputs each cycle (ADR-028 Hard
  Rule 6);
- is visible in `state/health.json`'s `run_status` block
  (`account_report_age_seconds`, `configured_max_account_state_age_seconds`,
  `account_state_fresh`) and `health_check.py`'s RUN STATUS panel,
  independently of whether the compliance gate itself ran that cycle.

Every existing caller that never threads `account_report_age_seconds`
through (the field defaults to `None`) keeps its prior, unaffected
behavior -- the gate only ever fires when a real age is supplied, which
`deployment_windows/start.py` always does in production.

## 9. Compliance day-one bootstrap can use a non-representative balance — CLOSED

**Closed by:** `titan_protocol/compliance_state_store/bootstrap.py`
(`is_account_verified_flat()`, `resolve_bootstrap_balance()`), wired
into `ComplianceStateStore.load_or_bootstrap()` and
`deployment_windows/start.py`'s `_build_compliance_account_state()`.

Previously, `load_or_bootstrap()` set `daily_starting_balance` and
`peak_balance` from whichever balance the *first-ever successful*
`/bridge/account` report carried -- unconditionally, only when the
persisted state file didn't exist yet (i.e. a fresh install, or state
deliberately cleared). If that first success was delayed (by WebRequest
instability, a slow first attach, etc.) until after the real trading day
had already started, and the account already had floating P&L or open
positions by then, the daily-loss baseline was bootstrapped from a
balance that didn't represent the true start-of-day value.

Fixed: bootstrap now proceeds only once the account is *verified flat*
-- no open positions (`bridge_engine.latest_positions` is empty) and
`balance` == `equity` within `flat_account_equity_tolerance` (default
0.01) -- the strongest signal available from wire data alone that the
reported balance hasn't been contaminated by trading activity already in
progress. Until that condition holds, `load_or_bootstrap()` returns
`None` and the caller skips the cycle entirely (the same fail-closed
convention already used for "no account state reported yet"), never
bootstrapping from a guess. An operator-supplied
`compliance.day_start_balance_override` (JSON config) bypasses
verification entirely and is used immediately and deterministically --
the escape hatch for the one contamination case wire data can never
reveal (see residual limitation below). Once a state file exists,
bootstrap verification is never re-evaluated -- restarts (before or
after trading, any time of day) behave exactly as before this fix.

**Residual limitation:** this closes the *open-position/floating-P&L*
contamination case, not a *closed*-trade one -- a trade opened and
closed earlier the same day, before Titan ever received a report, has
already changed `balance` permanently with no wire field to reveal it.
That case remains undetectable from wire data alone; an operator who
knows this happened should set `day_start_balance_override` for that
one bootstrap, or manually correct
`state/compliance_state.json`'s `daily_starting_balance` if it already
bootstrapped from such a snapshot.

## 10. HTTP poll had no backoff + undelivered commands blocked a pair for 20x longer than necessary — CLOSED

A live deployment reported the section 7 fixes working as designed
(transport pseudo-status failures correctly classified and logged) but
the underlying WebRequest() instability continuing, visible as
continuous per-second `TITAN_DIAG ATTEMPT`/failure lines in the Experts
log ("looping"), and separately asked whether this explains why Titan
wasn't trading. Two distinct, real defects were found, both fixed
(ADR-034 Amendment 5):

**Defect A — no backoff between polling cycles.** `HttpGet()`'s
`MaxRetries`/`RetryDelayMs` bounds retries *within* one
`/bridge/commands/poll` call, but `OnTimer()` (`mt5/TitanProtocolEA.mq5`)
called `PollAndExecuteCommands()` again every single tick (once per
second) regardless of the previous cycle's outcome, unlike
`EnsureSocketConnected()`'s own reconnect backoff for the Socket
transport. A persistently failing poll therefore retried at full
intensity forever — the actual mechanism behind the log spam.

**CLOSED:** `PollAndExecuteCommands()` now gates itself behind an
exponential backoff (`PollBackoffBaseDelayMs` × 2^attempt, capped at
`PollBackoffMaxDelayMs` — 500ms/1s/2s/4s/8s/15s, mirroring
`EnsureSocketConnected()`'s own technique), reset on the next successful
poll, HTTP-only (Socket's own backoff is untouched). A skipped tick
returns before even printing the `TITAN_DIAG ATTEMPT` line — the actual
elimination of per-tick spam.

**Defect B (the "why doesn't Titan ever trade" answer) — undelivered
commands were held in-flight 20x longer than necessary.** A
`TradeCommand` Compliance approves is enqueued into `CommandQueue`
independently of whether the EA ever successfully polls it.
`CommandQueue.poll()` silently drops a pending command once it exceeds
`BridgeConfig.command_ttl_seconds` (15s default) — the EA simply never
receives it, with no signal back to Runtime. `InFlightCommandRegistry.
has_unresolved()` had no way to distinguish "the EA is still working on
this" from "this command already vanished, undelivered, minutes ago" —
both looked identical (an entry present, not yet resolved) — so the pair
stayed blocked for the full in-flight `ttl_seconds` (300s,
`_IN_FLIGHT_COMMAND_TTL_SECONDS`) regardless. Under a persistently flaky
poll transport this reproduces indefinitely: submit, silently expire
undelivered within 15s, wait out most of a 5-minute window doing
nothing, resubmit, repeat — Compliance keeps approving entries that
never reach the market, with no error anywhere in the loop.

**CLOSED, then hardened (production-readiness review):** the first
version of this fix added `BridgeEngine.command_delivered()` (mirroring
`command_resolved()`) plus an `undelivered_grace_seconds` constructor
parameter and an `is_delivered` parameter on `reconcile()`. A pre-
production review flagged two correctness requirements this composition
didn't fully satisfy: (1) a delivered command must never be released
merely because it aged out of tracking; (2) the delivery check and queue
expiry must be race-safe against a `poll()` landing at nearly the same
moment. Both were real, since `is_delivered`/age were two independently-
timed reads across two different locks with no atomicity between them.

**Fixed:** `CommandQueue.is_abandoned(correlation_id, now)` (new)
replaces `is_delivered()` for this purpose — evaluated entirely under
`CommandQueue`'s own single lock, and once it concludes abandonment, it
permanently records that (`_abandoned_ids`), which `poll()` now also
checks and refuses to ever deliver — making "delivered" and "abandoned"
permanent, mutually exclusive outcomes regardless of which of
`poll()`/`is_abandoned()` a concurrent thread reaches first.
`InFlightCommandRegistry.reconcile()`'s `is_delivered`/
`undelivered_grace_seconds` parameters are replaced by a single
`is_abandoned` callable (`BridgeEngine.command_abandoned`) — the registry
no longer independently computes any age/grace threshold of its own for
this purpose. Verified with a real multi-threaded test racing
deliberately disagreeing clock readings 500 times
(`TestIsAbandonedConcurrencySafety`). See ADR-034 Amendment 6 for the
full trace.

**Also added:** `deployment_windows/verify_transport_configuration.py` —
answers "are the EA and Bridge actually running the same transport" from
real evidence only (never assumed): Bridge's configured
`bridge.transport`, the EA's own OnInit-resolved `Transport=` value, the
Bridge's actual bound listener(s), a per-request tally of the EA's own
`TITAN_DIAG ATTEMPT transport=` lines, and whether the EA's automatic
Socket→HTTP fallback (Amendment 3) fired — reusing
`diagnose_communication.py`'s own log-location/parsing helpers.

**Still open, not eliminated by this fix (never in scope for it):** the
underlying native `WebRequest()`/WinINet pseudo-status instability
(`1001`/`1003`, `GetLastError=5203`) itself — this fix stops it from
producing runaway log spam and from silently starving trade entries for
minutes at a time, but does not make the platform-level WinINet layer
itself reliable. **Superseded by Amendment 10 below:** the paragraph
above recommended the Socket transport as mitigation and pointed at
`verify_transport_configuration.py` to confirm it; both no longer exist
(Socket transport was removed entirely, and that tool along with it) —
see section 11.

## 11. Native socket transport removed entirely — HTTP is now the only transport (ADR-034 Amendment 10)

**What changed:** at the operator's explicit direction, after this exact
deployment's own field evidence showed *both* transports independently
failing on this VPS (Socket: `GetLastError=4014` despite a confirmed
allow-list entry and full terminal restarts; HTTP: `pseudoStatus=1001`/
`5203`, elapsed time exceeding `WebRequest()`'s own timeout — identical
to the failure section 7 above already documented), the operator chose
to remove Socket entirely and standardize on HTTP, modeled on the
original Phantom architecture. Full rationale, everything removed, and
everything explicitly preserved is documented in
`docs/adr/ADR-034-mt5-bridge-transport-hardening.md` Amendment 10 — not
duplicated here.

**Practical effect on every socket-related item elsewhere in this
document:** section 7's and section 10's own mentions of
`bridge.transport`/`Transport=Socket`/`verify_transport_configuration.py`
now describe removed code, kept above only as an accurate historical
record of what those fixes did *at the time* — do not act on them as
current configuration guidance. There is no `transport` field to set
anymore; `bridge.port`/EA `BackendUrl` are the only address configuration
that exists.

**Still open, unchanged by this amendment:** the underlying
`WebRequest()`/WinINet pseudo-status instability itself (`1001`/`1003`,
`GetLastError=5203`) is a property of this VPS/terminal's environment,
not of Titan Protocol's code, and this amendment does not and cannot fix
it — it only removes the Socket transport that had been mitigating it.
Continuing to operate on this VPS with HTTP as the sole transport is the
operator's own accepted risk, made with full knowledge of this history.

## 12. WinINet proxy/WPAD diagnostic for `WebRequest()` failures — new tool, underlying issue remains OPEN (operator-side, VPS environment)

**What this adds:** section 11 above states the WinINet-layer
`WebRequest()` instability (`pseudoStatus=1001`/`5203`) is an environment
property, not a code bug, and that removing Socket transport does not
fix it. `deployment_windows/diagnose_wininet.py` gives the operator a
concrete way to actually diagnose and, in the common case, fix it,
rather than leaving it as an unexplained dead end.

**What it does:** `WebRequest()` resolves through Windows' WinINet
stack — the same layer governed by Internet Explorer's "Internet
Options" (proxy configuration, WPAD auto-detection, PAC scripts). This
applies to `127.0.0.1` calls unless loopback is explicitly exempted from
proxy resolution. A well-documented cause of exactly this failure
signature is "Automatically detect settings" (WPAD) or a configured
proxy adding multi-second delay (or an outright failure) to every
WinINet request, including calls to the operator's own machine. The
script reads the operator's proxy registry state
(`ProxyEnable`/`ProxyServer`/`ProxyOverride`/`AutoConfigURL`) and times a
request to the Bridge's `/bridge/heartbeat` twice — once proxy-aware,
once with the proxy explicitly bypassed — so the operator gets a
measured timing delta as evidence, not a guess.

**What `--fix` does and does not do:** if run with `--fix`, it adds
`127.0.0.1` and `<local>` to `ProxyOverride` so loopback traffic skips
proxy resolution, then re-times the request to prove the change actually
helped. It never touches `ProxyEnable` or `ProxyServer` — the deployment
may still need the real proxy for its own external calls (Trading
Economics/Forex Factory), so the fix is scoped to loopback exemption
only, never a blanket proxy disable.

**Known limitation, stated up front rather than silently:** the script
can read registry-configured proxy settings but cannot evaluate a PAC
(Proxy Auto-Config) script the way WinINet itself does — Python's
`urllib` does not execute JScript. If `AutoConfigURL` is set, the script
flags this explicitly so the operator knows to inspect the PAC script or
add an explicit bypass instead of trusting the tool's own coverage.

**Still open:** this is a diagnostic and a narrowly-scoped fix for the
single most common cause (proxy/WPAD adding delay to loopback traffic).
It does not guarantee resolution of every possible WinINet failure mode
on every VPS — the operator must run it on the actual Windows machine
and report back what it finds, since this cannot be exercised
end-to-end outside that environment.

## 13. Risk Engine reservation-ledger leak — CLOSED; positions-staleness observability — new diagnostic, underlying gap remains OPEN

**Reservation-ledger leak (CLOSED):** `RiskEngine.ReservationLedger`
reservations were created on every approved trade (`reserve_if()`) but
`release_reservation()` had no production caller — reservations leaked
permanently, until the portfolio-heat gate began falsely rejecting
legitimate trades (quantified against this repo's own config defaults:
5–60 approved trades to saturation, depending on confidence-tier
sizing). `InFlightCommandRegistry` now carries each trade's
`reservation_id` through its existing lifecycle (one authoritative
ownership model, not a second state machine) and releases it at every
terminal/confirmed state: compliance rejection, an already-in-flight
pair re-reserving every blocked cycle, bridge submission failure,
execution rejection, abandonment, plain TTL expiry, and — only once
real exposure is proven — position confirmation or its fail-safe
timeout. A guaranteed exception-safety cleanup path in
`RuntimeOrchestrator` releases the reservation if a failure occurs
before ownership transfers to the registry. `pending_reservation_count`/
`pending_reservation_total_r` are now surfaced in `health.json`'s
`run_status` block and `health_check.py`'s RUN STATUS panel. Verified
by 14 deterministic tests covering every release point, restart
behavior, exposure double-counting, repeated-release idempotency, and a
regression test reproducing the original false-rejection defect —
Integration Verified; not yet runtime- or production-observed.

**Positions-staleness observability (new tool, underlying gap
remains OPEN):** section 3 above already notes that
`positions_are_live` (heartbeat health) is a proxy for positions
freshness, not a proof — `/bridge/positions` can fail specifically
while `/bridge/heartbeat` keeps succeeding, since the EA sends them as
two independent `WebRequest()` calls (confirmed against
`mt5/TitanProtocolEA.mq5`'s `OnTimer()`/`SendHeartbeat()`/
`SendPositions()`). A new structured log,
`positions_stale_despite_healthy_heartbeat`, now fires exactly when
heartbeat is healthy and the last successful positions refresh exceeds
`BridgeConfig.heartbeat_timeout_seconds` — edge-triggered with
periodic-repeat rate-limiting (no log flooding during a sustained
outage) and wrapped in a dedicated fault-containment guarantee
(`_safe_log_exception()`) so the diagnostic itself can never crash the
live-cycle loop. This is observability only — no trade
acceptance/rejection behavior changed. The underlying lifecycle
question (whether/how to react once this condition is confirmed to
actually occur) remains open, deferred pending the real runtime
evidence this signal is now positioned to collect.

## Everything else in this release is fully implemented

Setup, dependency installation, folder/configuration/write-access
verification (including the new `data\` folder), compileall, import
smoke test, Bridge startup and bind verification, Reliability
monitoring (including real Bridge command-queue depth via
`ReliabilityEngine.report_queue_depth`), graceful/forced stop scoped to
exactly one recorded pid, restart sequencing, health checking (Bridge,
Runtime, Reliability, configuration, API-key-env-var presence,
news-feed trust state, queue health, duplicate-process detection), MT5
file installation with automatic `.set` personalization (short of
MetaEditor compilation, which requires the real GUI), and desktop
shortcut creation (Windows only) are all real, working, and were
exercised end-to-end in this environment before this release was sent.
