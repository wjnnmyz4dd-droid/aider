# ADR-037 Production Activation Plan

**Status:** Drafted — implementation-ready, pending independent Plan review.
**Governs:** the coordinated production activation of ADR-037 (ORB
cross-pair session opportunity selection), consuming the values and
process decisions already closed by
`docs/plans/adr-037-production-activation-policy-decision.md` (Accepted
policy, independently reviewed and confirmed conformant).
**This document is a PLAN. It does not itself implement, configure, or
activate anything.** No file it describes has been created or modified
by this drafting pass. Its own Validation section (§16) proves that.

---

## 0. Baseline (re-verified fresh, this pass)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `94a0f0b` ("ADR-037:
  record Gate A pair list and Gate B anchor decision"), tracking
  `origin/claude/phantom-ea-visibility-cjjf3a`, working tree clean before
  this pass began.
- Governing history on this HEAD: `254e9d6` → `aed4e65` (stale-window
  correction) → `ea53932` (research) → `cea4a96` (policy, partial) →
  `94a0f0b` (policy, finalized). The policy document at `94a0f0b` carries
  the disposition "ADR-037 PRODUCTION ACTIVATION POLICY DEFINED — READY
  FOR INDEPENDENT POLICY REVIEW" and was independently reviewed
  (conforms) before this Plan was authorized to be drafted.
- Gate A (`titan_protocol/strategy_engine/config.py::DEFAULT_APPROVED_
  PAIRS_BY_STRATEGY`): `OPENING_RANGE_BREAKOUT` absent — re-confirmed by
  direct read of the current file (0 entries for that `StrategyId`).
- Gate B (`titan_protocol/evidence_engine/config.py::EvidenceEngineConfig.
  opening_range_anchors`): defaults to `()`; shipped example config's
  `evidence_engine` section carries no `opening_range_anchors` key (falls
  back to the empty default).
- `OpportunitySelectionEngineConfig`: `enabled_windows=()`,
  `cross_pair_selection_enabled=False`, `tie_tolerance=0.5` — re-confirmed
  unchanged.
- `deployment_windows/start.py:1143` still hardcodes
  `OpportunitySelectionEngineConfig()` with no config-loading path — the
  known, unclosed prerequisite this Plan's §4 closes.
- `deployment_windows/start.py`'s `main()` argparse defines only
  `--config` and `--foreground` — **no `--dry-run` flag or mechanism
  exists anywhere in `start.py` today** (re-confirmed by grep across
  `deployment_windows/*.py` for `dry.run|dry_run|DRY_RUN|--dry`: the only
  hit is an unrelated whitelist-bypass flag in `install.py`). This is a
  new prerequisite this Plan's §6 specifies closing.
- `deployment_windows/config_loader.py::DeploymentSettings` has no
  `opportunity_selection_config` field. The `opening_range_anchors`
  JSON-array-to-tuple parsing block (lines ~418–443) already exists and
  is the direct template §4 mirrors.
- `titan_protocol/strategy_engine/config.py` docstring (ADR-026 Hard Rule
  5): `approved_pairs_by_strategy` is **read-only at runtime — no JSON
  config-loading path exists or is planned for it**; every one of the 5
  legacy strategies' pair lists is a hardcoded Python constant, edited by
  redeploying source, never by editing the deployment JSON. Gate A
  activation is therefore **a source-code change**, not a JSON-config
  change — this is existing, established precedent (identical treatment
  to every other strategy's pair list), not a new asymmetry introduced by
  this Plan.
- `deployment_windows/config/titan_protocol_config.example.json`:
  `bridge.allowed_symbols` = `["EURUSD","GBPUSD","USDJPY","USDCHF",
  "AUDUSD","USDCAD","NZDUSD"]` — already a superset of the decided Gate A
  list; no change required there.
- `RuntimeOrchestrator.__init__` (`titan_protocol/runtime/engine.py:113`)
  accepts `bridge_submit: Optional[BridgeSubmit] = None` — already
  supports a no-submit construction. `start.py:1281-1287` currently
  passes the real `bridge_submit` closure positionally. `CycleOutcome.
  SUBMITTED` (`titan_protocol/runtime/models.py:106`) is still reported
  even when `bridge_submit is None` — a pre-existing, already-documented
  observability nuance (Research §4), not a defect this Plan fixes.
- `validate_profile()` (`titan_protocol/runtime/validation.py`) performs
  exactly 4 ADR-037-specific checks, confirmed unchanged: (1) every
  `enabled_windows` entry references a real `opening_range_anchors` entry
  and its `session_name` matches — unconditional; (2) every Gate B anchor
  is referenced by some enabled window — only when the flag is `True`;
  (3) `enabled_windows` non-empty — only when the flag is `True`; (4)
  Gate A width `>1` — only when the flag is `True`. No 5th check exists
  for Bridge-symbol/Gate-A cross-consistency (the policy's own
  acknowledged gap, C2).
- Architecture-check scope confirmed: `scripts/check_architecture.py`
  only scans `phantom_pipeline/` — irrelevant to this Plan.
  `tests/titan_protocol/runtime/test_architecture.py` only scans
  `titan_protocol/runtime/` for forbidden identifiers/imports — the files
  this Plan touches (`deployment_windows/config_loader.py`,
  `deployment_windows/start.py`) are outside that scan's package root
  and are therefore unaffected by it.
- `tests/titan_protocol/bridge/test_structural_boundary.py`'s
  `allowed_prefixes` already covers `deployment_windows/start.py`,
  `deployment_windows/config_loader.py`,
  `deployment_windows/config/titan_protocol_config.example.json`,
  `deployment_windows/KNOWN_GAPS.md`, `deployment_windows/
  WINDOWS_OPERATOR_GUIDE.md`, `titan_protocol/`, `tests/titan_protocol/`,
  and `tests/deployment_windows/test_config_loader.py` individually. It
  does **not** yet cover this new file
  (`docs/plans/adr-037-production-activation-plan.md`) — this Plan's own
  commit adds that one entry, following the file's own established
  convention (mirrors the two entries already added for the Research and
  Policy Decision artifacts).
- Fresh validation re-run this pass (read-only): `python3 -m compileall
  titan_protocol tests deployment_windows` clean;
  `tests/titan_protocol/opportunity_selection_engine` (68),
  `tests/titan_protocol/runtime` (189), and the 2 structural-boundary
  suites (architecture + bridge, 27 tests combined) all green; `git
  status` clean before and during source inspection (no edits made).

## 1. Governing production policy values (restated verbatim, not re-decided)

- **Gate A** (`approved_pairs_by_strategy` entry for
  `StrategyId.OPENING_RANGE_BREAKOUT`): `EURUSD, GBPUSD, USDJPY`.
- **Gate B** (`opening_range_anchors` entries, `(SessionName, start_hour_
  utc, start_minute_utc)`):
  `(SessionName.LONDON, 8, 0)`,
  `(SessionName.LONDON_NEW_YORK_OVERLAP, 13, 0)`,
  `(SessionName.EARLY_NEW_YORK, 13, 30)`.
- **`enabled_windows`** (one `EnabledOpportunityWindow` per Gate B anchor
  above, `enabled=True`, `anchor_hour_utc`/`anchor_minute_utc` matching
  the anchor exactly): 3 entries, one per session above.
- **`cross_pair_selection_enabled`**: `True` (only once all of the above
  are populated together — see §5).
- **Ranking**: score-only, no secondary criterion (unchanged).
- **Tie policy**: Option A, tie → no winner, tolerance `0.5` inclusive
  `<=` (unchanged).
- **Initial session set**: exactly these 3 windows — London, London–New
  York Overlap, Early New York. No 4th window, no different anchors, no
  different pairs are authorized by this Plan. Changing any of these
  values is a product-policy decision, not an implementation detail —
  out of this Plan's scope (§14).

## 2. Actual current activation surfaces — file-impact-matrix-oriented inspection

Confirmed by direct, fresh reads of the current tree (not inferred from
prior reports):

| Surface | Current state | Gap this Plan closes |
|---|---|---|
| `titan_protocol/strategy_engine/config.py::DEFAULT_APPROVED_PAIRS_BY_STRATEGY` | No `OPENING_RANGE_BREAKOUT` entry | Add the Gate A entry (source-code change; ADR-026 Hard Rule 5 precedent) |
| `deployment_windows/config/titan_protocol_config.example.json::evidence_engine.opening_range_anchors` | Absent (defaults to `()`) — **already JSON-configurable**, no code change needed | Populate the 3 Gate B anchors as a config-only change |
| `deployment_windows/config/titan_protocol_config.example.json` | No `opportunity_selection_engine` section exists | Add new section + config-loading code (this is the real gap) |
| `deployment_windows/config_loader.py::DeploymentSettings` | No `opportunity_selection_config` field | Add field + parsing function (§4) |
| `deployment_windows/start.py:1143` | Hardcodes `OpportunitySelectionEngineConfig()` | Replace with `settings.opportunity_selection_config` |
| `deployment_windows/start.py` `main()` argparse | Only `--config`, `--foreground` | Add `--dry-run` (§6) |
| `deployment_windows/start.py` `bridge_submit` closure (~line 1255) | Always calls the real `bridge_engine.submit_command` | Branch on dry-run: pass `None` instead |
| `titan_protocol/runtime/validation.py::validate_profile()` | 4 ADR-037 checks, no Bridge/Gate-A cross-check | **Deliberately unchanged** — see §5's explicit decision |
| `deployment_windows/KNOWN_GAPS.md` | No entry documents the OSE config-loading gap | Add a dated entry once §4 closes it |
| `deployment_windows/WINDOWS_OPERATOR_GUIDE.md` | No activation/dry-run runbook section | Add one (§7, §9 procedures) |
| `tests/deployment_windows/test_config_loader.py` | No OSE-section tests | Add tests (§11) |
| `tests/titan_protocol/bridge/test_structural_boundary.py` | Missing this Plan's own path | Add 1 entry for `docs/plans/adr-037-production-activation-plan.md` |

## 3. OSE config-loading gap — exact closure specification

**Configuration ownership:** the Opportunity Selection Engine owns its
own JSON section, `opportunity_selection_engine`, in the same
`titan_protocol_config.json` file that already owns every other engine's
section (`evidence_engine`, `strategy_engine`, etc.) — per the reviewed
policy's C1, mirroring the established per-engine-owns-its-config
pattern.

**JSON shape:**
```json
"opportunity_selection_engine": {
  "cross_pair_selection_enabled": false,
  "tie_tolerance": 0.5,
  "enabled_windows": [
    {"session": "LONDON", "anchor_hour_utc": 8, "anchor_minute_utc": 0, "enabled": true}
  ]
}
```
`enabled_windows` defaults to `[]` if the key is absent (mirrors
`opening_range_anchors`'s own `.get(..., [])` convention). `cross_pair_
selection_enabled` defaults to `False`, `tie_tolerance` to `0.5` — both
via `_get_bool`/`_get_float` (already-existing helpers, reused, not
reimplemented).

**Parsing path** (new function `_parse_opportunity_selection_config`,
or inlined in `load_settings()` directly after the `evidence_engine`
block — implementer's choice, no behavioral difference):
1. `ose_section = _section(data, "opportunity_selection_engine")` —
   missing section defaults to `{}` (existing `_section()` convention,
   unchanged).
2. `raw_windows = ose_section.get("enabled_windows", [])`; `ConfigError`
   if not a `list`.
3. For each entry (indexed, for error messages): must be a `dict`;
   `session` validated via `SessionName.__members__` membership exactly
   like `opening_range_anchors`'s own `session` key (raising `ConfigError`
   with the invalid value and the full valid-name list on failure);
   `anchor_hour_utc`/`anchor_minute_utc` validated as non-bool `int`
   (raising `ConfigError` on type mismatch, mirroring `start_hour_utc`/
   `start_minute_utc`'s existing pattern exactly); `enabled` validated via
   `_get_bool`-equivalent inline check, defaulting to `True` if absent.
4. Construct `EnabledOpportunityWindow(session_name=SessionName[session],
   anchor_hour_utc=anchor_hour_utc, anchor_minute_utc=anchor_minute_utc,
   enabled=enabled)` per entry.
5. Construct `OpportunitySelectionEngineConfig(enabled_windows=tuple(...),
   tie_tolerance=_get_float(ose_section, "tie_tolerance", 0.5),
   cross_pair_selection_enabled=_get_bool(ose_section, "cross_pair_
   selection_enabled", False))` inside the same `try/except ValueError`
   wrapping pattern the `evidence_engine`/`strategy_engine` blocks already
   use, re-raising as `ConfigError` (so a duplicate-anchor-key
   `ValueError` from `OpportunitySelectionEngineConfig.__post_init__`
   surfaces as a normal fail-closed config error, not an uncaught
   exception — same treatment every other section already gets).
6. Add `opportunity_selection_config: OpportunitySelectionEngineConfig`
   to `DeploymentSettings` (new field) and thread it through `load_
   settings()`'s final `return DeploymentSettings(...)` call.
7. **Missing section**: defaults to fully inert (`enabled_windows=()`,
   `cross_pair_selection_enabled=False`) — identical behavior to today's
   hardcoded default, so an existing deployment's config file that has
   never heard of this section keeps working unchanged (backward
   compatible by construction, not by special-casing).
8. **Malformed value** (wrong type, unknown `SessionName`, non-int
   hour/minute): fails closed at config-load time with a `ConfigError`
   naming the exact offending key and value — startup refuses, matching
   every other section's existing malformed-value treatment. No default
   silently substituted for a malformed (as opposed to absent) value.
9. **Duplicate `(anchor_hour_utc, anchor_minute_utc)` window**: already
   caught by `OpportunitySelectionEngineConfig.__post_init__`'s own
   existing uniqueness check — re-raised as `ConfigError` per step 5, not
   re-implemented in the parser.
10. **Interaction with `validate_profile()`**: no change to
    `validate_profile()` itself — it already accepts an `Optional[
    OpportunitySelectionEngineConfig]` and runs its 4 existing checks
    against whatever `start.py` constructs and passes it. Wiring
    `settings.opportunity_selection_config` through in place of the
    hardcoded default is the entire integration; `validate_profile()`'s
    logic requires zero edits (re-confirmed: it already reads the config
    it's handed, not a hardcoded one).
11. **Backward compatibility**: an operator who never edits their config
    file for this section gets `enabled_windows=()`, `cross_pair_
    selection_enabled=False` — byte-for-byte the same inert state
    `start.py:1143`'s hardcoded default produces today. No deployment is
    affected by this change unless it explicitly populates the new
    section.

`start.py:1143`'s replacement:
```python
opportunity_selection_config = settings.opportunity_selection_config
```
(dropping the hardcoded `OpportunitySelectionEngineConfig()` call and its
surrounding "safe migration default" comment, which becomes the config
file's own responsibility to document instead).

## 4. Coordinated activation contract

**The five inputs that must reach their production values together:**
Gate A (`approved_pairs_by_strategy`), Gate B (`opening_range_anchors`),
`enabled_windows`, `cross_pair_selection_enabled`, and Bridge-symbol
availability (`bridge.allowed_symbols`).

**Mechanically, these are NOT all the same kind of change:**
- Gate A is a **source-code** change (`titan_protocol/strategy_engine/
  config.py`) — per §0's re-confirmed ADR-026 Hard Rule 5 precedent, this
  cannot be a JSON-config change without a separate ADR amendment
  authorizing a new config-loading surface for `approved_pairs_by_
  strategy`, which is explicitly out of scope (§14). Gate A activation
  therefore requires a code commit and a redeploy of the running
  service, exactly like every other strategy's pair list already does.
- Gate B, `enabled_windows`, and `cross_pair_selection_enabled` are
  **deployment-JSON-config** changes (`titan_protocol_config.json` on the
  target host) — Gate B already has a working JSON path today (§2's
  table); `enabled_windows`/`cross_pair_selection_enabled` gain one via
  §3.
- Bridge-symbol availability is **already satisfied** by the shipped
  example config (`bridge.allowed_symbols` is a superset of Gate A) — no
  change required for this specific pair list, but a **manual runbook
  verification step** is still mandatory (per policy C2) because no
  automated cross-check exists (see the explicit decision immediately
  below).

**"One verified deployment change" (policy C2) therefore means: one
coordinated release** — a single code commit carrying the Gate A source
change, deployed together with a single config-file edit carrying Gate
B + `enabled_windows` + the flag, such that the very first `start.py`
boot after the release either runs with all five inputs at their
production values, or (if any one is missing) fails closed at `validate_
profile()` before any trading path is reachable. It does not require the
code deploy and the config edit to be the literal same file-write
operation — it requires that no intermediate boot state exists where the
flag is `True` while Gate A/B/`enabled_windows` are only partially
populated. `validate_profile()`'s checks 2–4 already enforce exactly this
for Gate B/`enabled_windows`/Gate-A-width (fail-closed, unconditional on
boot); the only production input those checks cannot verify is whether a
Gate A pair also has real market data / Bridge symbol authorization.

**Explicit decision on Bridge/Gate-A automated cross-check (required by
this task, not left silent): NOT added by this Plan.** The reviewed
policy (C2) already made this decision at the process level — it
requires a **manual runbook check**, not a new automated `validate_
profile()` check — and named this as a "reasonable future hardening
candidate," not something the Activation Plan must build. Adding a 5th
`validate_profile()` check now would exceed this Plan's scope (a new
safety mechanism beyond what the Policy authorized) and is unnecessary
for the current Gate A list specifically, since §0 already confirms all
3 Gate A pairs are already in `bridge.allowed_symbols` for the shipped
example config — the manual check has a knowable, verifiable answer
today. §15 records this as a resolved-by-precedent decision, not a
blocker: the runbook step (§9) is mandatory and sufficient for this
Plan's scope; a future hardening pass may automate it without touching
ADR-037's activation semantics.

**Fail-closed behavior per named partial state** (all independently
derived from `validate_profile()`'s existing 4 checks — re-verified,
none require new logic):

| Partial state | Boot outcome |
|---|---|
| Flag `True`, `enabled_windows` empty | Check 3 fails: `ConfigValidationResult.valid=False`, `start.py` prints `FAILED:` and returns exit code 2 before any engine construction beyond validation completes. |
| Flag `True`, Gate B anchor referenced by `enabled_windows` but not present in `opening_range_anchors` | Check 1 fails (unconditional check, also fires when flag is `False`) — same fail-closed exit. |
| Flag `True`, Gate B anchor present but not referenced by any `enabled_windows` entry | Check 2 fails — same fail-closed exit. |
| Flag `True`, Gate A width `<=1` | Check 4 fails — same fail-closed exit. |
| Flag `False`, any/all of Gate A/B/`enabled_windows` populated | No check fires (checks 2–4 gated on the flag) — fully inert, boots clean, matches the migration-safe default already in production today. |
| Gate A pair not in `bridge.allowed_symbols` | **Not detected by any startup check** (the acknowledged gap) — the pair silently never becomes an ORB candidate (no market data ingested for it); this is a silent no-op, not a crash, and is the reason the manual runbook check (§9) is mandatory before flipping the flag. |
| Bridge symbol present, Gate A absent | No effect — pair never considered by ORB; legacy strategies for it, if any, unaffected. |
| Malformed `enabled_windows` JSON entry | Config-load time `ConfigError`, before `validate_profile()` even runs — process exits before engine construction. |
| Config file specifies `enabled_windows` for a session whose anchor also exists but `session_name` mismatches the anchor's own `SessionName` | Check 1's second clause fails (`session_name` mismatch) — fail-closed exit. |

## 5. Mandatory dry-run gate

**Purpose:** verify the exact intended production configuration is
mechanically correct end-to-end (config loads, `validate_profile()`
passes, the live cycle runs, ORB candidates are evaluated, a winner is
selected and persisted, no exception, no crash) — **a correctness/safety
gate, not a profitability gate.** No trading-performance threshold (win
rate, P&L, Sharpe) is invented or required by this gate; that is
explicitly out of scope (this Plan does not perform ADR-035 Phase 5 or
Quant Validation Engineer work).

**Launch mechanism (new — does not exist today, per §0):** add a
`--dry-run` flag to `start.py`'s `main()` argparse. When set, `bridge_
submit` (the closure at ~line 1255) is replaced with `None` instead of
the real `bridge_engine.submit_command` closure, and `RuntimeOrchestrator`
is constructed with `bridge_submit=None` — every other input (Gate A/B,
`enabled_windows`, the flag, all engines, all config) is byte-for-byte
identical to the intended live-activation config. This reuses
`RuntimeOrchestrator`'s already-tested `bridge_submit=None` construction
path (§0) — no new orchestrator code is required, only the CLI plumbing
that swaps which closure gets passed. The Bridge HTTP server itself still
starts and listens (so EA polling/health-check behavior is exercised
too) — only the final `submit_command` call is suppressed.

**PASS criteria (all required):**
1. Process starts and stays up for the full observation window (§ below)
   with no uncaught exception or crash-restart.
2. `validate_profile()` reports `valid=True` at boot for the exact
   intended production config (Gate A/B/`enabled_windows`/flag all at
   their §1 values).
3. Log evidence of at least one full `run_cycle()` per pair per
   configured session window during the observation period, with no
   `ERROR`-level log entries attributable to the OSE/ORB path.
4. At least one `superseded_opportunity_window_encountered` absence check
   — i.e., confirm this signal does **not** fire spuriously across a
   normal day's session transitions (it firing would indicate a Gate-B/
   session-window misconfiguration, not a code defect, but is still a
   dry-run abort condition per this Plan's correctness scope).
5. `CycleOutcome.SUBMITTED` is expected to appear in logs even though no
   real submission occurs (the known, already-documented `bridge_
   submit=None` observability nuance, §0) — the dry-run runbook must
   explicitly state this so an operator does not mistake it for an actual
   live submission or for a false-positive bug.
6. `state/opportunity_selection_winners.json` (or the configured
   equivalent state file) shows persisted winner entries consistent with
   expected ORB candidate qualification during the observation window —
   confirms `OpportunityWinnerStore.decide_once()` is reachable and
   functioning against real market data.

**FAIL criteria (any one is disqualifying):** any uncaught exception;
`validate_profile()` reporting `valid=False`; any `ERROR`-level log
attributable to OSE/ORB; the Bridge HTTP server failing to bind/serve;
zero `run_cycle()` evidence across the observation window for any
configured pair/session combination that should have been reachable
given real market hours.

**Observation window:** at minimum, one full trading day spanning all 3
configured session windows (London 08:00, Overlap 13:00, Early NY 13:30
UTC) so every Gate B anchor is exercised at least once. A shorter window
does not exercise all 3 windows and is insufficient proof.

**Proof requirement:** the dry-run's logs and the resulting `state/
opportunity_selection_winners.json` snapshot are retained and attached to
the activation authorization record (§7's step 2) — an operator's verbal
confirmation alone is not sufficient proof.

## 6. Live activation procedure (ordered, minimum 10 steps)

1. **Preflight**: confirm the dry-run (§5) passed with all 6 PASS
   criteria met and its proof artifacts retained.
2. **Independent activation review/authorization**: obtain the explicit,
   separate authorization this Plan itself does not grant (§16's
   Implementation Sequence Phase E) — this step is a governance gate, not
   a technical one.
3. **Freeze the target config**: prepare the exact production
   `titan_protocol_config.json` with Gate B anchors, `enabled_windows`
   (all 3, `enabled=true`), and `cross_pair_selection_enabled=true`
   populated at their §1 values — identical to what was dry-run tested,
   not a fresh edit.
4. **Manual Bridge/Gate-A cross-check** (§4's named runbook step,
   required before proceeding): confirm every Gate A pair (`EURUSD,
   GBPUSD, USDJPY`) is present in the target deployment's actual
   `bridge.allowed_symbols` — not merely the example config's.
5. **Deploy the Gate A source-code change**: merge/deploy the commit
   adding `OPENING_RANGE_BREAKOUT` to `DEFAULT_APPROVED_PAIRS_BY_
   STRATEGY` with the §1 pairs. Until step 7, `cross_pair_selection_
   enabled` in the running config is still `False` — Gate A alone with
   the flag `False` is inert (§4's partial-state table), so this step, by
   itself, changes nothing observable yet.
6. **Stop the running `start.py` process** cleanly (existing shutdown
   procedure, unchanged).
7. **Replace the config file** with the frozen production config from
   step 3.
8. **Start `start.py` normally (no `--dry-run`)**. `validate_profile()`
   runs at this boot against the real config; if any check fails, the
   process exits before the Bridge listener binds and before any engine
   reaches a state where it could submit — **this is the exact point
   before which live Bridge submission is impossible.**
9. **The exact point live Bridge submission becomes possible**: the
   first successful `run_cycle()` after this boot, for a pair/session
   combination where ORB wins the opportunity-selection cascade, passes
   Risk/Compliance, and `bridge_submit` (now the real closure, not
   `None`) is invoked. Before step 8's successful `validate_profile()`
   pass, submission is structurally unreachable; after it, submission
   follows the pipeline's existing, unmodified decision path exactly as
   it does for the 5 legacy strategies today.
10. **Post-activation verification** (§8): confirm boot logs show
    `valid=True`, confirm the Bridge HTTP server is listening, confirm
    `run_status`/health diagnostics report normally, and begin the §8
    observation period.

## 7. Rollback / failure handling (10 named failure classes)

| # | Failure | Handling |
|---|---|---|
| 1 | `validate_profile()` fails at the step-8 boot | Process already exited (exit code 2) before any trading path opened — no rollback needed beyond reverting the config file to the last known-good version and restarting. |
| 2 | Gate A source deploy (step 5) succeeds but config replacement (step 7) is delayed/fails | Running process still has `cross_pair_selection_enabled=False` in its live config (old config file) — **fully inert**, exactly the pre-activation state; Gate A being "broadened" in source alone changes nothing observable, confirmed by the fail-closed table in §4 — **this is the explicit trace requested**: broadening Gate A alone, with the flag still `False`, is safe by construction because checks 2–4 never fire and no code path reads `approved_pairs_by_strategy` for ORB except through the OSE cascade, which itself requires `cross_pair_selection_enabled=True` to be reachable at all (confirmed by tracing `evaluate_window()`'s caller in the runtime barrier — the cascade is skipped entirely when the flag is `False`, independent of Gate A's width). |
| 3 | Config replacement (step 7) succeeds but is malformed | `ConfigError` at load time, before `validate_profile()` — process refuses to start; revert config file, restart. |
| 4 | Bridge HTTP server fails to bind after step 8 | Existing, pre-ADR-037 failure path (`start.py` already returns exit code 2 on bind failure) — unchanged by this Plan; revert and restart. |
| 5 | Post-activation, a Gate A pair turns out to be missing from the real `bridge.allowed_symbols` (step 4's check was performed incorrectly) | Silent no-op for that pair (§4's table) — not a crash. Remediation: add the symbol to `bridge.allowed_symbols` and restart, or set `cross_pair_selection_enabled=False` to fully deactivate while investigating. |
| 6 | Post-activation, `superseded_opportunity_window_encountered` fires unexpectedly and repeatedly | Indicates a Gate-B/session misconfiguration or an unanticipated same-`SessionName`-distinct-anchor collision (F2, confirmed non-applicable to the current 3-window plan, §0) — investigate before assuming a rollback is needed; if confirmed a real defect, set `cross_pair_selection_enabled=False` (full rollback, item 7). |
| 7 | **Full rollback**: set `cross_pair_selection_enabled=false` in the config, restart | Re-confirms `validate_profile()`'s checks 2–4 stop firing (gated on the flag); the running deployment returns to the exact same inert state as pre-activation **regardless of whether Gate A/B/`enabled_windows` are left populated** — this is the explicit non-assumed trace requested: the flag alone gates every ADR-037-specific check and the entire OSE evaluation call in the runtime barrier, so setting it `False` is a complete, sufficient rollback even with a "broadened" Gate A left in place; the persisted `opportunity_selection_winners.json` state file is inert data that is simply not read again while the flag is `False` (`OpportunityWinnerStore` is only ever invoked from `OpportunitySelectionEngine.evaluate_window()`, itself only ever invoked from the runtime barrier gated on the flag). |
| 8 | Partial rollback attempted (Gate B anchors removed but `enabled_windows` left referencing them, flag still `True`) | Check 1 fails at next boot (unconditional) — fail-closed, forces a complete config fix before restart succeeds; cannot leave the system in a half-rolled-back live state. |
| 9 | Rollback of the Gate A **source** change (removing the `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` entry) while the flag is still `True` in the deployed config | Check 4 fails at next boot (Gate A width `<=1`) — fail-closed; the two rollback mechanisms (flag flip vs. source revert) are independently sufficient and mutually fail-safe, not required to be sequenced. |
| 10 | Dry-run process (§5) itself crashes or hangs during observation | No production impact — `bridge_submit=None` means no live orders were ever reachable; treat as a dry-run FAIL, fix the underlying defect, and re-run the full dry-run observation window from the start (a partial re-run does not satisfy §5's PASS criteria). |

## 8. DST / operator procedure for fixed-UTC anchors

Gate B's anchors (`08:00`, `13:00`, `13:30` UTC) are **fixed UTC clock
values with no DST adjustment mechanism** — re-confirmed: `EvidenceEngineConfig.opening_range_anchors` stores raw
`(hour, minute)` integers compared directly against UTC-normalized bar
timestamps; no timezone-aware or DST-aware logic exists anywhere in
`titan_protocol/evidence_engine/` or `titan_protocol/opportunity_
selection_engine/`, and this Plan does **not** invent any. The values
were chosen (per the reviewed policy) as fixed UTC anchors deliberately
— London/New York local-session clock times shift by an hour twice a
year (US and UK/EU DST transitions do not always align on the same
calendar date), which means the sessions these anchors were named for
(London open, the Overlap, Early New York) will drift relative to these
fixed UTC values during the few weeks per year when UK and US DST
transitions are offset from each other. **This Plan does not resolve
that drift** — doing so would require new anchor-scheduling architecture
(a product/deployment decision or ADR amendment, not an implementation
detail) and is explicitly out of scope. **Operator procedure**: this is
recorded as a known, accepted operational characteristic — no anchor
value changes automatically; if operators want the anchors to track a
local-session definition through DST transitions, that is a future
product decision (§15) requiring an explicit new anchor-scheduling
design, not a per-transition manual edit improvised here. No manual
DST-day recalculation procedure is specified because none is required by
the current fixed-UTC policy — the anchors simply stay at `08:00/13:00/
13:30 UTC` year-round, by design.

## 9. Adversarial activation matrix (27 scenarios)

| # | Scenario | Startup outcome | Risk/Bridge reachable? |
|---|---|---|---|
| 1 | Fresh deployment, no config changes at all | Boots clean, fully inert (today's default) | No (ORB never selected) |
| 2 | Gate A source deployed, config untouched (flag `False`) | Boots clean, inert | No |
| 3 | Gate B anchors added to config, flag `False`, `enabled_windows` empty | Boots clean, inert (checks 2-4 gated on flag) | No |
| 4 | `enabled_windows` populated (3 entries), flag `False` | Boots clean, inert | No |
| 5 | Flag `True`, everything else at §1 production values, Gate A source deployed | Boots clean, ORB reachable | Yes, if ORB wins cascade + passes Risk/Compliance |
| 6 | Flag `True`, `enabled_windows` empty | Check 3 fails, exit 2 | No |
| 7 | Flag `True`, Gate B anchors empty, `enabled_windows` non-empty | Check 1 fails (no matching anchor), exit 2 | No |
| 8 | Flag `True`, Gate A source not yet deployed (width 0) | Check 4 fails (`0 <= 1`), exit 2 | No |
| 9 | Flag `True`, Gate A source deployed but only 1 pair added (violates §1, hypothetical) | Check 4 fails (`1 <= 1`), exit 2 | No |
| 10 | Flag `True`, 1 Gate B anchor present, 1 `enabled_windows` entry references a *different* anchor | Check 1 fails on the mismatched entry, exit 2 | No |
| 11 | Flag `True`, anchor present, `enabled_windows` entry's `session_name` doesn't match the anchor's own `SessionName` | Check 1's session-mismatch clause fails, exit 2 | No |
| 12 | Flag `True`, 2 of 3 Gate B anchors referenced by `enabled_windows`, 3rd anchor present but unreferenced | Check 2 fails, exit 2 | No |
| 13 | Flag `True`, `enabled_windows` has an `enabled=false` entry for one of the 3 windows | Boots clean (check 2/3 only look at anchor coverage/non-emptiness, not per-window `enabled`); that specific window is structurally present but the engine's own `evaluate_window()` — re-confirm this is enforced at evaluation time via the `enabled` field, not startup, since `validate_profile()` never inspects it) — that window simply never produces a winner at runtime | Partially — 2 of 3 windows reachable |
| 14 | All 5 coordinated inputs (Gate A, Gate B, `enabled_windows`, flag, Bridge symbols) at §1 production values simultaneously | Boots clean, fully as designed | Yes |
| 15 | Gate A pair (`USDJPY`) missing from `bridge.allowed_symbols` on a given host | Boots clean (no startup check exists) — silent no-op for that pair | No, for that pair only; EURUSD/GBPUSD unaffected |
| 16 | A 4th, unauthorized Gate B anchor added by a future change without updating this Plan's authorized 3-window scope | Boots clean if internally consistent (no check limits *how many* windows), but is a policy violation, not a code failure — this Plan authorizes exactly 3, no more | Yes, but out of policy scope — flag as a governance violation, not caught by any technical gate |
| 17 | `--dry-run` flag combined with `cross_pair_selection_enabled=True` and full production values | Boots clean, ORB reachable in evaluation, `bridge_submit=None` suppresses real submission | No (by design — this is the dry-run gate itself) |
| 18 | Restart mid-session after a winner was already persisted for today's London window | `OpportunityWinnerStore`'s persisted-winner lookup returns the existing winner unconditionally (post-stale-window-correction behavior, re-confirmed) — no re-evaluation, no duplicate winner | Same as before restart (already-decided pair, if any, remains eligible for downstream Risk/Compliance) |
| 19 | Two of the three windows' anchors accidentally set to overlapping times in a hypothetical future misconfiguration | `_validate_no_overlapping_anchors` (Evidence Engine's own existing check, unconditional, independent of ADR-037's flag) fails at config-load time, before `validate_profile()` even runs | No |
| 20 | Malformed `enabled_windows` JSON (`anchor_hour_utc` as a string) | `ConfigError` at config-load time | No |
| 21 | Malformed `enabled_windows` JSON (unknown `SessionName` string) | `ConfigError` naming the invalid value and valid list | No |
| 22 | Duplicate `(anchor_hour_utc, anchor_minute_utc)` in `enabled_windows` | `ConfigError` via `OpportunitySelectionEngineConfig.__post_init__`'s existing uniqueness check | No |
| 23 | Operator edits only Gate B (adds 3 anchors) intending to also flip the flag, but forgets, on a config that already had `enabled_windows` populated from a previous partial rollout attempt | Depends on whether `enabled_windows` was already populated — if yes and flag is `False`, boots clean, inert (flag gates everything); confirms flag is the true single point of activation, not anchor/window presence | No, while flag is `False` |
| 24 | Operator sets the flag `True` in a config where `tie_tolerance` was also edited to a negative value | `OpportunitySelectionEngineConfig.__post_init__`'s existing `tie_tolerance < 0.0` check raises `ValueError`, surfaced as `ConfigError` at config-load time | No |
| 25 | Full rollback (`cross_pair_selection_enabled=False`) applied while Gate A source and Gate B/`enabled_windows` config all remain in place | Boots clean, fully inert — re-confirms §7 item 7's trace: the flag alone gates the entire cascade | No |
| 26 | Dry-run (`--dry-run`) run against a config where the flag is still `False` | Boots clean; OSE cascade never evaluated (flag gates it, independent of `--dry-run`) — this specific combination proves nothing about ORB's dry-run readiness and must not be mistaken for a valid dry-run proof | No (and no ORB evaluation to observe either — an invalid dry-run for this Plan's purposes) |
| 27 | Live activation (no `--dry-run`) attempted without ever having completed a passing dry-run per §5 | Technically boots and trades if `validate_profile()` passes — **this is a process/governance violation, not a technical one**: §6 step 1 (preflight) requires the dry-run to have already passed; nothing in `validate_profile()` itself can detect "was a dry-run run first," so this is enforced by the activation authorization gate (§6 step 2), not by code | Yes, technically — which is exactly why §6's ordered procedure and §16 Phase E's separate authorization exist |

## 10. Test / proof matrix

| Requirement | Automated test | Manual/operator proof |
|---|---|---|
| OSE JSON section parses correctly (valid input) | New test in `tests/deployment_windows/test_config_loader.py` | — |
| Missing section defaults inert | New test, same file | — |
| Malformed `session`/`anchor_hour_utc`/`anchor_minute_utc`/`cross_pair_selection_enabled`/`tie_tolerance` raise `ConfigError` | New tests, same file (mirrors existing `opening_range_anchors` malformed-value tests) | — |
| Duplicate anchor key raises `ConfigError` | New test, same file | — |
| `start.py` uses `settings.opportunity_selection_config` instead of the hardcoded default | Existing `validate_profile()`/OSE construction tests still pass unchanged; a targeted assertion that the hardcoded call site is gone (code review, not a runtime test) | Code review of the diff |
| `--dry-run` flag exists and suppresses submission | New test asserting `bridge_submit` is `None` (or an equivalent no-submit sentinel) when `--dry-run` is passed, without requiring a live Bridge connection | Full dry-run observation window (§5) |
| `validate_profile()`'s 4 existing checks are unchanged | Existing test suite (`tests/titan_protocol/runtime/`) re-run, all green, no new failures | — |
| Fail-closed partial-state table (§4) | Existing `test_opportunity_selection_structural_readiness.py` and `validate_profile()` test coverage already exercise checks 1-4; re-confirm all pass unchanged | — |
| Rollback via flag flip is complete (§7 item 7) | Existing runtime barrier tests already confirm the OSE cascade is skipped when the flag is `False`; re-run to reconfirm no regression | — |
| Bridge/Gate-A manual cross-check | — | Runbook step (§6 step 4), documented in `WINDOWS_OPERATOR_GUIDE.md` |
| DST drift is accepted, not silently wrong | — | Documented in `WINDOWS_OPERATOR_GUIDE.md` / this Plan (§8) as an operator-facing known characteristic |
| Dry-run PASS criteria (§5) | — | Operator-executed dry-run, logs + state-file snapshot retained as proof |
| Structural-boundary scope (this Plan's own diff) | `tests/titan_protocol/bridge/test_structural_boundary.py` (extended with 1 new allowed-prefix entry for this Plan's own file) | — |

## 11. Implementation sequence

- **Phase A — activation-support code/config loading**: §3's OSE
  config-loading closure (`config_loader.py`, `start.py`'s hardcoded-call
  replacement, example config's new inert-default section) + §5's
  `--dry-run` flag and `bridge_submit` branch. Gate A/B values are **not**
  written into any config or source constant during Phase A — Phase A
  ships with the section present but still defaulting to the inert
  state, exactly like every other engine's config section does today.
- **Phase B — automated tests/structural validation**: §10's new/updated
  tests, `test_structural_boundary.py`'s own allowed-prefix extension for
  Phase A's files (already covered, per §0 — no new entries needed there,
  only for this Plan document itself), full regression run.
- **Phase C — production configuration preparation**: prepare (but do
  not deploy) the target `titan_protocol_config.json` with Gate B/
  `enabled_windows`/flag at §1 values, and prepare the Gate A source
  commit — both reviewed but not yet merged/deployed to the live host.
- **Phase D — mandatory dry run**: execute §5 in full against the
  prepared Phase C configuration using `--dry-run`, for the full
  required observation window, collecting proof artifacts.
- **Phase E — independent activation review/authorization**: a separate,
  explicit authorization — reviewing Phase D's proof artifacts and this
  Plan's own conformance — that this Plan does **not** itself grant.
- **Phase F — live activation**: §6's ordered procedure. **This Plan does
  NOT authorize Phase F to be performed automatically by whatever
  implementation pass follows it.** Phase F requires Phase E's separate
  authorization, obtained after this Plan's own independent review
  additionally confirms.
- **Phase G — post-activation verification**: §6 step 10 / §7's
  observation and rollback-readiness confirmation.

**The implementation pass that follows this Plan performs Phases A-D
only, unless a separate, explicit authorization for Phase E/F is given.**

## 12. Exhaustive file-impact matrix

| File | Change | Rationale |
|---|---|---|
| `deployment_windows/config_loader.py` | Add `opportunity_selection_config` field to `DeploymentSettings`; add OSE section parsing | §3 |
| `deployment_windows/start.py` | Replace hardcoded `OpportunitySelectionEngineConfig()` with `settings.opportunity_selection_config`; add `--dry-run` flag; branch `bridge_submit` on it | §3, §5 |
| `deployment_windows/config/titan_protocol_config.example.json` | Add `opportunity_selection_engine` section with inert defaults (Phase A) — **Gate A/B production values are NOT written here by Phase A** (§11) | §3 |
| `titan_protocol/strategy_engine/config.py` | Add Gate A entry to `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` — **only at Phase F (live activation), not Phase A** | §1, §6 |
| `tests/deployment_windows/test_config_loader.py` | New OSE-section parsing tests | §10 |
| A new or extended test asserting `--dry-run` suppresses submission | Likely `tests/deployment_windows/test_config_loader.py` or a new `tests/deployment_windows/test_start_dry_run.py` (implementer's choice; if a new file, `test_structural_boundary.py`'s `allowed_prefixes` needs one more entry at that time) | §5, §10 |
| `deployment_windows/KNOWN_GAPS.md` | Add a dated entry documenting the OSE config-loading gap as CLOSED once Phase A ships | §2 |
| `deployment_windows/WINDOWS_OPERATOR_GUIDE.md` | Add activation runbook section (manual Bridge/Gate-A check, dry-run procedure, DST note) | §6, §8, §9 |
| `tests/titan_protocol/bridge/test_structural_boundary.py` | Add 1 entry for `docs/plans/adr-037-production-activation-plan.md` (this Plan's own commit) | §0 |
| `docs/plans/adr-037-production-activation-plan.md` | This document | — |
| **Deliberately unchanged**: `titan_protocol/runtime/validation.py` | No new checks added (§4's explicit decision) | §4 |
| **Deliberately unchanged**: `titan_protocol/opportunity_selection_engine/*` | Stale-window/supersession design from `aed4e65` is final for this Plan's scope | §14 |
| **Deliberately unchanged**: `titan_protocol/evidence_engine/config.py` | No anchor-hour/minute range validation added (ADR-035 Phase 5 residual risk, out of scope) | §14 |
| **Deliberately unchanged**: `scripts/check_architecture.py` | Scans `phantom_pipeline/` only, irrelevant | §0 |

## 13. Explicit scope-boundary preservation

Not touched, redesigned, or decided by this Plan: ADR-036 legacy-strategy
retirement conditions/timeline; runner-up fallback; ADR-035 Phase 5
(config-loader/example-config/cross-field-validation work for the
non-ORB strategies, or the anchor-hour/minute range-validation residual
risk); `StrategyId` cardinality (no new strategy added or removed);
legacy strategy implementations (untouched); ranking/tie policy (already
Accepted product decision, unchanged); opportunity-window identity
semantics (`range_start`-keyed, unchanged from `aed4e65`); the 3-window
initial session set (fixed at exactly London/Overlap/Early-New-York, no
4th window authorized); Gate A/B values themselves (already decided,
this Plan only specifies how to write them in, not what they are).

## 14. Plan-level unresolved blockers

- **None are safety-critical or activation-critical** — every decision
  needed to execute Phases A-D is derivable from Accepted governance
  (ADR-037 + Amendment 1, ADR-026 Hard Rule 5, the reviewed Policy
  Decision) plus direct source precedent (the `opening_range_anchors`
  parsing pattern). Classified below per the task's required taxonomy:

| Item | Classification |
|---|---|
| Exact new test file name/location for the `--dry-run` suppression test | Implementation detail, safely resolved by precedent (mirror `tests/deployment_windows/test_config_loader.py`'s existing structure, or add a new file following the same module-per-`deployment_windows/*.py`-file convention already established) |
| Whether the OSE JSON parsing is a standalone function or inlined in `load_settings()` | Implementation detail, safely resolved by precedent (both patterns already coexist in `config_loader.py`; either satisfies §3) |
| Bridge/Gate-A automated cross-check | Explicitly NOT required by this Plan (§4) — recorded as a future hardening candidate, not a blocker |
| DST-aware anchor scheduling | Product/deployment decision required if ever wanted — explicitly out of scope for this Plan (§8); current fixed-UTC behavior is accepted as-is, not a blocker to Phases A-F as specified |
| A 4th/different session window in the future | Product-policy decision required (§13) — not a blocker to activating the already-decided 3 |
| Whether Phase E/F authorization uses a written sign-off, a specific reviewer role, or another mechanism | Process detail left to whoever performs Phase E — this Plan requires only that it be separate and explicit (§11), not a specific mechanism; not safety-critical since Phase F cannot proceed without it regardless of its exact form |

No item above requires an ADR amendment.

## 15. Fresh validation (documentation-only pass)

- `python3 -m compileall titan_protocol tests deployment_windows` — clean.
- `python3 -m unittest discover -s tests/titan_protocol/opportunity_selection_engine` — 68 tests, all green.
- `python3 -m unittest discover -s tests/titan_protocol/runtime` — 189 tests, all green.
- `python3 -m unittest tests.titan_protocol.bridge.test_structural_boundary tests.titan_protocol.runtime.test_architecture` — both green after this Plan's own file is added to the allow-list.
- Direct verification (in-memory, fresh): `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` still has 0 entries for `OPENING_RANGE_BREAKOUT` (Gate A untouched by this documentation-only pass); `EvidenceEngineConfig().opening_range_anchors == ()` (Gate B untouched); `OpportunitySelectionEngineConfig().cross_pair_selection_enabled is False`; `len(list(StrategyId)) == 6`; `build_default_registry(...)` still contains exactly 5 legacy strategies, ORB absent.
- `git status` — clean except this one new documentation file (plus the one-line `test_structural_boundary.py` allow-list addition made alongside it).

## 16. Commit / disposition

This diff is confined to: this new Plan document, and the one-line
addition to `tests/titan_protocol/bridge/test_structural_boundary.py`'s
`allowed_prefixes` tuple required for it to pass. No production
configuration, source constant, or activation flag was written by this
pass.

---

**This pass authorizes no production activation.** Even though this Plan
is being finalized as implementation-ready, Gate A/B population,
`cross_pair_selection_enabled=True`, and live Bridge submission remain
prohibited until: (1) an implementation pass builds Phases A-D exactly as
specified here; (2) the mandatory dry-run (§5) passes against the real
target deployment; and (3) Phase E's separate, explicit activation
authorization is obtained. This Plan's own finalization is not that
authorization.

**ADR-037 PRODUCTION ACTIVATION PLAN FINALIZED — READY FOR INDEPENDENT PLAN REVIEW**
