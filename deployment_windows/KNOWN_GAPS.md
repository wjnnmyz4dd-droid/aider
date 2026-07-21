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
trace and architecture comparison. Purely in-memory (a process restart
loses in-flight tracking) -- no regression versus before, since
`CommandQueue` itself is also in-memory-only.

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
