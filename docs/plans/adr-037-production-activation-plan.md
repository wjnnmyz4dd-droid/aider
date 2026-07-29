# ADR-037 Production Activation Plan

**Status:** Revised (safety-critical sequencing/rollback correction) —
pending independent Plan re-review.
**Governs:** the coordinated production activation of ADR-037 (ORB
cross-pair session opportunity selection), consuming the values and
process decisions already closed by
`docs/plans/adr-037-production-activation-policy-decision.md` (Accepted
policy, independently reviewed and confirmed conformant).
**This document is a PLAN. It does not itself implement, configure, or
activate anything.** No file it describes has been created or modified
by this drafting pass or this revision pass. Its own Validation section
(§16) proves that.

**Revision history:**
- Drafted at commit `cb07916` — disposition "READY FOR INDEPENDENT PLAN
  REVIEW."
- Independently reviewed: disposition "REQUIRES REVISION" — blocking
  finding F1 (safety-critical): the Plan incorrectly treated
  `cross_pair_selection_enabled=False` as sufficient to make a broadened
  Gate A inert. Direct source trace and an executable reproduction (§4)
  prove this is false whenever `enabled_windows` is empty or fails to
  cover an ORB candidate's `range_start` — an independently-qualified
  ORB winner takes the ordinary non-participating path straight into
  `_run_back_half()`, and this happens **per pair, independently**, so
  multiple Gate A pairs can reach Risk/Compliance/Bridge in the same
  cycle with zero cross-pair arbitration. Non-blocking finding F2: no
  regression test exercised this combination. This revision corrects
  both — see §15 (Findings-resolution table).

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
- **This revision's own fresh baseline** (re-verified from source, not
  from the prior review's report): `titan_protocol/runtime/engine.py`'s
  `run_cycle()` gates the cross-pair barrier's *participation* on
  `enabled_range_starts` (built from `opportunity_selection_config.
  enabled_windows` at lines 619-626) — **this population loop never
  reads `cross_pair_selection_enabled`.** `check_eligibility()`
  (`strategy_engine/eligibility.py`) gates ORB's own per-pair candidacy
  purely on `approved_pairs_by_strategy` (Gate A) — nothing else. An
  executable reproduction (§4) confirms these two facts compose into a
  genuine defect in this Plan's original sequencing/rollback claims —
  not a hypothetical reading of the code.

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

### 4.0 Corrected safety invariant (supersedes the original §4/§7 claims)

**Reproduced from source, executably, not merely reasoned about.** A
standalone script constructing the real `RuntimeOrchestrator`,
`OpportunitySelectionEngine`, and `OpportunityWinnerStore` (no mocks
below the Runtime layer) with 3 pairs (EURUSD/GBPUSD/USDJPY) each
independently producing a `QUALIFIED` ORB `winning_strategy` in the same
cycle proves:

| Scenario | Gate A | `enabled_windows` | flag | Outcome (observed) |
|---|---|---|---|---|
| A | broad (3 pairs) | **empty** | `False` | **All 3 pairs `SUBMITTED`; `risk_engine.call_count == 3`.** Each pair independently reaches `_run_back_half()` via the ordinary non-participating path (`window is None` for every candidate, since `enabled_range_starts` is empty) — zero cross-pair arbitration. |
| B | broad (3 pairs) | populated, covers all anchors | `False` | Only the highest-scoring pair `SUBMITTED` (`EURUSD`); the other 2 `NOT_SELECTED_OPPORTUNITY_WINDOW`; `risk_engine.call_count == 1`. The barrier arbitrates correctly **even with the flag at its default `False`**, because `enabled_range_starts` population and barrier participation depend only on `enabled_windows`, never on the flag. |
| C | broad (3 pairs) | populated, covers all anchors | `True` | Identical to B (`call_count == 1`). The flag makes **no observable difference** to barrier arbitration once `enabled_windows` already covers Gate A. |
| D | closed (today's production default — 0 pairs) | irrelevant | `False` | ORB can never be `winning_strategy` for any pair (`check_eligibility()` returns `NOT_ELIGIBLE` before `qualify()` ever runs) — whatever each pair's real winning strategy is (a legacy strategy, here) proceeds independently and normally; this is ordinary, intended, pre-ADR-037 behavior, unrelated to the barrier. |

**Conclusion, stated as the corrected invariant:**

> **Barrier coverage (`enabled_windows`, covering every anchor a broad
> Gate A can produce a candidate for) is the safety-bearing mechanism —
> not `cross_pair_selection_enabled`.** A running deployment must never
> expose a broadened, multi-pair ORB Gate A unless Gate B and
> `enabled_windows` are *already* present and mutually consistent, such
> that every intended ORB anchor is barrier-covered. `cross_pair_
> selection_enabled` is not, by itself, the safety barrier.

This corrects the original Plan's central error (an assumption, never
independently proven, that the flag gated the barrier itself). Nothing
here changes Runtime's actual code or semantics — the invariant is a
**deployment/sequencing discipline this Plan must enforce operationally**,
not a code defect requiring a fix (§8 examines whether a code change
would still be worth adding, and recommends against it for this Plan's
scope).

### 4.1 What `cross_pair_selection_enabled` actually controls (§7 task requirement)

Precisely, from source, superseding the original Plan's "the flag gates
the cascade" framing:
1. `validate_profile()` checks 2–4 (anchor-coverage-by-flag, non-empty
   `enabled_windows`, Gate A width `>1`) — **structural strictness at
   startup, enforced only when the flag is `True`.** With the flag
   `False`, these three checks are skipped entirely (check 1 remains
   unconditional, but it only validates `enabled_windows` entries
   against real anchors — it never inspects Gate A at all).
2. The `anchor_not_enabled_while_selection_active` runtime signal
   (`engine.py:693-698`): when the flag is `True` **and** an ORB winner's
   `range_start` matches no `enabled_windows` entry, that candidate is
   suppressed (fail-closed, distinct log signal, `NOT_SELECTED_
   OPPORTUNITY_WINDOW`) instead of proceeding. When the flag is `False`,
   the identical mismatch proceeds unchanged (scenario A above).

So the flag is a genuine, **defense-in-depth backstop** for anchors the
operator did *not* anticipate at config-authoring time (a future 4th
Gate B anchor added without a matching `enabled_windows` entry; a clock/
DST edge case producing an unexpected `range_start`) — it is not, and
was never claimed by ADR-037's own text to be, the primary mechanism
that makes multi-pair Gate A safe. That mechanism is, and always was,
`enabled_windows` coverage. The Plan's final target state still requires
the flag `True` (§1, unchanged) precisely for this backstop value — this
revision does not remove or redesign the flag, and no ADR amendment is
implicated: ADR-037 §11/§12's own text already describes both the
structural-readiness checks and the anchor-not-enabled signal in these
exact terms; the original Plan simply mischaracterized their relationship
to Gate A width.

### 4.2 The five inputs (unchanged from the original Plan)

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

**"One verified deployment change" (policy C2), corrected: it means Gate
B + `enabled_windows` must already be running and verified in the live
deployment *before* Gate A's source change is ever deployed to that same
instance** — not "no intermediate boot state where the flag is `True`
while Gate A/B/`enabled_windows` are only partially populated," which is
the original, now-superseded framing. `validate_profile()`'s checks 2–4
protect only the flag-`True` states (§4.1); they provide **zero
protection** for the flag-`False`, broad-Gate-A, empty-`enabled_windows`
state (scenario A above) — that state boots perfectly cleanly today,
which is exactly the danger. The corrected requirement is therefore an
**operational sequencing discipline** (§6), not merely a startup-check
guarantee: Gate A must never become broad in a running instance except
at a moment when `enabled_windows`/Gate B already cover it. The only
production input no code check verifies at all is whether a Gate A pair
also has real market data / Bridge symbol authorization (§9 below,
unchanged from the original Plan).

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

### 4.3 Corrected partial-state table

**Superseding the original table in full.** For every row, "startup
succeeds" is a `validate_profile()`/`ConfigError` fact (verified against
source); "ORB eligible" reflects `check_eligibility()` reading Gate A
alone; "barrier arbitrates" and "multiple pairs can independently reach
Risk" are the facts the §4.0 reproduction directly demonstrates —
**never inferred from the flag's value.**

| # | State | Startup succeeds? | ORB eligible? | Barrier arbitrates? | Multiple ORB pairs can independently reach Risk? | Allowed by the activation procedure (§6)? |
|---|---|---|---|---|---|---|
| P1 | Gate A closed, config absent | Yes | No (Gate A empty) | N/A | No | Yes — today's production default |
| P2 | Gate A closed, Gate B/`enabled_windows` prepared, flag `False` | Yes (check 1 passes trivially; checks 2-4 skipped) | No | N/A (no ORB candidates possible) | No | **Yes — this is the required Phase C "prepare while Gate A stays closed" state** |
| P3 | Gate A closed, Gate B/`enabled_windows` prepared, flag `True` | **No — check 4 fails** (Gate A width `<=1`) | No | N/A | No | No — cannot even boot; `validate_profile()` itself forbids setting the flag before Gate A is broad, which is why the flag can only ever be set *at or after* the Gate A deploy, never before |
| P4 | Gate A broad, Gate B/`enabled_windows` **fully prepared and covering**, flag `False` | Yes | Yes | **Yes — reproduced (scenario B): 1 winner, `call_count=1`** | **No** | **Yes — this is the safe intermediate state immediately after the Gate A source deploy, before the flag flip** |
| P5 | Gate A broad, Gate B/`enabled_windows` fully prepared and covering, flag `True` | Yes (all 4 checks pass) | Yes | Yes — reproduced (scenario C): identical to P4 | No | Yes — the final target state (§1) |
| P6 | **Gate A broad, `enabled_windows` empty** | Yes — **no check catches this** | Yes | **No barrier — every ORB win takes the non-participating path** | **Yes — reproduced (scenario A): all 3 pairs `SUBMITTED`, `call_count=3`** | **No — forbidden. This was the original Plan's unrecognized danger state.** |
| P7 | Gate A broad, `enabled_windows` partial (covers some but not all 3 anchors) | Yes — no check catches the uncovered anchor(s) when flag is `False`; **if flag is `True`, check 2 fails** (uncovered Gate B anchor) | Yes | Arbitrates only for the covered anchor(s); the uncovered anchor's candidates take the unarbitrated path exactly like P6 | **Yes, for whichever anchors remain uncovered** | No — forbidden under flag `False`; impossible to boot under flag `True` |
| P8 | Gate A broad, Gate B missing entirely | Yes if `enabled_windows` is also empty (vacuously "covered"); **`ConfigError` at config-load time if `enabled_windows` references anchors that don't exist** | Yes | No barrier (no anchors, no windows) | Yes, same as P6 | No |
| P9 | Gate A broad, an `enabled_windows` entry references an anchor whose own `SessionName` doesn't match | Yes if flag `False` (check 1 unconditional — **actually fails closed even here**, since check 1 runs regardless of the flag) → **`validate_profile()` correctly refuses to boot in this specific case** | N/A (never boots) | N/A | No | No — and this is the one partial-misconfiguration case the *existing* unconditional check 1 already catches regardless of the flag |
| P10 | Config rollback (reverting Gate B/`enabled_windows`) attempted while Gate A remains broad | Depends on order — see §7 Rollback C | Yes | Depends — if `enabled_windows` is cleared/reduced first, reproduces P6/P7 before Gate A is ever reverted | **Yes, if the config rollback removes barrier coverage before Gate A is closed** | No — forbidden ordering; §7 specifies the safe order |

**The single sentence that corrects the original Plan:** *P4 and P6 are
both "Gate A broad, flag `False`" — the original table conflated them
into one row ("fully inert"). They are opposite in every safety-relevant
respect. The only variable that distinguishes them is `enabled_windows`
coverage, not the flag.*

### 4.4 Facts unaffected by this revision (preserved from the original Plan)

- **Malformed `enabled_windows` JSON entry** (wrong type, unknown
  `SessionName`, non-int hour/minute): `ConfigError` at config-load time,
  before `validate_profile()` even runs — process exits before engine
  construction. Unchanged.
- **Gate A pair not in `bridge.allowed_symbols`**: not detected by any
  startup check — the pair silently never becomes an ORB candidate (no
  market data ingested for it). This is orthogonal to F1: a missing
  Bridge symbol makes that pair's scan *incomplete* (it can never
  produce a candidate at all, so it can neither win the barrier nor take
  the unarbitrated path) — it does not, by itself, enable unarbitrated
  execution; if anything it silently *removes* a pair from Gate A's
  practical reach. F1's danger requires the Bridge symbol to be present
  (so the pair can actually trade) — see §9 for the settled manual
  cross-check, which this revision does not reopen.
- **Bridge symbol present, Gate A absent**: no effect — pair never
  considered by ORB; legacy strategies for it, if any, unaffected.
  Unchanged.

### 4.5 Structural-readiness (`validate_profile()`) re-assessed against the corrected sequencing

**Re-checked directly against source, not assumed.** `validate_profile()`
does **not** protect the P6 state (broad Gate A, empty `enabled_windows`,
flag `False`) — confirmed by the §4.0 reproduction booting cleanly with
`valid=True`. This is not a new finding changing this revision's
approach; it is the precise fact F1 is about, and this revision's answer
is **operational sequencing (§6), not a new code check** — for the
following reasons, in order of priority per this task's "prefer the
minimum mechanism" instruction:

1. **A code check here would have to inspect a cross-engine combination
   `validate_profile()` doesn't currently need**: today, `validate_
   profile()`'s ADR-037-specific checks only run when the flag is
   `True` — this is itself a deliberate design choice (§4.1) so that an
   inert deployment (flag `False`) is never subject to structural strictness
   it doesn't need. Making the checks *also* fire when the flag is `False`
   but Gate A is broad would be a **behavior change to `validate_profile()`
   itself**, not merely wiring an existing check through — squarely a new
   safety mechanism, which the reviewed Policy (C3) already decided
   `validate_profile()` "is sufficient and must not be... worked around,"
   without separately authorizing new checks beyond what it already has.
2. **The operational sequencing fix (§6) is sufficient and doesn't require
   any code change**: the corrected order guarantees `enabled_windows`
   is already staged and verified before Gate A is ever broadened at the
   live instance — P6 is simply never reached if the procedure is
   followed, independent of whether `validate_profile()` could also catch
   it.
3. **If this Plan's independent reviewer or a future hardening pass
   judges a code check worth adding anyway** (e.g., "warn — or even fail
   closed — whenever Gate A width `>1` and `enabled_windows` doesn't
   cover every anchor, regardless of the flag"), that is explicitly
   identified here as **a Plan change requiring its own authorization**,
   not something this revision implements. It would arguably strengthen
   defense-in-depth (catching P6/P7 even if the runbook procedure is
   someday not followed) without touching ADR-037's product-policy
   values — a plausible **future hardening candidate**, recorded in §14,
   not built now.

**This revision's position, stated plainly**: the minimum mechanism that
satisfies Accepted governance today is the corrected §6 sequencing. A
new `validate_profile()` check is not required to close F1, and is not
added by this revision — but it is not ruled out for a future pass
either, and is recorded honestly as a real option rather than dismissed.

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

**This revision's correction: the dry-run build is the first place Gate
A is ever broadened in a running instance — and this is safe regardless
of §4.0's invariant, by construction, not by exception to it.** The
dry-run instance must run with Gate A source **already** at its §1 value
(3 pairs), Gate B/`enabled_windows` fully populated and covering, and the
flag `True` — i.e. the complete intended final production state — so the
dry run actually proves the barrier arbitrates correctly (§4.0 scenario
C), not merely that nothing submitted. `bridge_submit=None` makes Bridge
submission structurally unreachable in this instance independent of Gate
A/barrier state (confirmed at `engine.py:422`: `self.bridge_submit is
not None and compliance.ready_for_bridge` — `None` short-circuits
unconditionally), so this dry-run instance can never itself trigger
F1's danger even if it were misconfigured. **This dry-run instance is
separate from, and never becomes, the live production instance** — Phase
F (§11) governs when Gate A is deployed to the instance that can
actually submit.

**PASS criteria (all required):**
1. Process starts and stays up for the full observation window (§ below)
   with no uncaught exception or crash-restart.
2. `validate_profile()` reports `valid=True` at boot for the exact
   intended production config (Gate A/B/`enabled_windows`/flag all at
   their §1 values — Gate A genuinely broad in this build, per above).
3. Log evidence of at least one full `run_cycle()` per pair per
   configured session window during the observation period, with no
   `ERROR`-level log entries attributable to the OSE/ORB path.
4. **Barrier arbitration proof**: when 2+ of the 3 Gate A pairs
   independently qualify ORB for the same enabled window in the same
   cycle, logs/state confirm exactly one winner reaches
   `CycleOutcome.SUBMITTED` and the others show
   `NOT_SELECTED_OPPORTUNITY_WINDOW` — the corrected §4.0 scenario C
   behavior, observed against real market data, not merely asserted.
5. **Tie behavior proof**: if two qualifying candidates' scores fall
   within `tie_tolerance` (`0.5`, inclusive `<=`) during the observation
   window, confirm neither reaches `SUBMITTED` (tie → no winner,
   unchanged product policy) — if no natural tie occurs during the
   window, this must be confirmed via the existing automated test suite
   (§10) rather than invented as a live-data requirement.
6. **Incomplete-scan fail-closed proof**: confirm from logs that a cycle
   in which any tracked pair fails to reach a terminal front-half outcome
   closes the whole window (`NOT_SELECTED_OPPORTUNITY_WINDOW` for every
   pending candidate) rather than partially resolving it — if this
   doesn't occur naturally, rely on §10's existing automated coverage
   (`TestIncompleteScanFailsClosed`) instead of forcing it live.
7. At least one `superseded_opportunity_window_encountered` absence check
   — i.e., confirm this signal does **not** fire spuriously across a
   normal day's session transitions (it firing would indicate a Gate-B/
   session-window misconfiguration, not a code defect, but is still a
   dry-run abort condition per this Plan's correctness scope).
8. `CycleOutcome.SUBMITTED` is expected to appear in logs even though no
   real submission occurs (the known, already-documented `bridge_
   submit=None` observability nuance, §0) — the dry-run runbook must
   explicitly state this so an operator does not mistake it for an actual
   live submission or for a false-positive bug.
9. `state/opportunity_selection_winners.json` (or the configured
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
the activation authorization record (§6 step 6, Phase E) — an operator's
verbal confirmation alone is not sufficient proof.

## 6. Live activation procedure (corrected sequencing — 12 steps)

**Superseding the original 10-step procedure in full.** The original
order (deploy Gate A source, *then* replace the config) is exactly the
sequence that produces §4.0 scenario A (P6) — a broadened, unarbitrated
Gate A running against an empty `enabled_windows` — for the entire
interval between the Gate A deploy and the config replacement. The
corrected order stages barrier coverage in the **live instance** first,
while Gate A stays closed there, and only deploys Gate A once that
coverage is already running and verified.

1. **Phase A/B complete**: activation-support code (§3, §5) is deployed
   and tested; Gate A remains closed (P1); nothing observable changes.
2. **Stage the config (Phase C)**: replace the live instance's
   `titan_protocol_config.json` with Gate B anchors and `enabled_windows`
   (all 3, matching, `enabled=true`) populated at their §1 values, while
   `cross_pair_selection_enabled` stays `False` and Gate A source
   remains closed. Restart `start.py` with this config.
3. **Verify the staged state is actually running (P2)**: confirm
   `validate_profile()` reports `valid=True`; confirm from the running
   process's own config (not a copy) that `enabled_windows` has exactly
   3 entries matching Gate B — Gate A is still closed, so this state is
   provably inert (`check_eligibility()` rejects every pair for ORB
   regardless of anything else). Record a fingerprint (hash or mtime) of
   this exact config file for step 8's stale-config check.
4. **Manual Bridge/Gate-A cross-check** (§4's named runbook step,
   unaffected by this revision): confirm every Gate A pair (`EURUSD,
   GBPUSD, USDJPY`) is present in the target deployment's actual
   `bridge.allowed_symbols` — not merely the example config's.
5. **Mandatory dry run (Phase D, §5)**: execute the dry-run build — a
   **separate instance**, `bridge_submit=None`, with Gate A *already*
   broadened in that build's source *and* the same staged Gate B/
   `enabled_windows`/flag=`True` config from step 2 — for the full
   observation window. Retain proof artifacts. This is safe by
   construction (submission unreachable regardless of Gate A/barrier
   state, §5) and additionally satisfies §4.0's invariant (barrier
   coverage complete throughout).
6. **Independent activation review/authorization (Phase E)**: obtain the
   explicit, separate authorization this Plan itself does not grant
   (§11) — reviewing step 5's proof artifacts and this Plan's own
   conformance. This step is a governance gate, not a technical one.
7. **(Phase F begins here.) Re-verify the staged live-instance config is
   still exactly what step 3 fingerprinted** — nothing may have drifted
   between staging and authorization.
8. **Deploy the Gate A source-code change to the live instance and
   restart.** *Precondition, required before this step is considered
   complete (the explicit stale-config risk this revision must address):*
   the redeploy mechanism must not touch, overwrite, or replace the
   staged JSON config file from step 2 — after the restart, **re-verify
   the running config's fingerprint still matches step 3's** before
   proceeding. If the redeploy process cannot guarantee this (e.g., a
   packaging step that reverts to a bundled example config), this step
   is not safe to consider complete until that guarantee exists — this
   is a deployment-hygiene precondition, not new production code.
   Immediately after this restart, the live state is P4 (§4.3): Gate A
   broad, barrier fully covering, flag still `False` — confirmed safe
   (§4.0 scenario B: arbitration works, `call_count` reflects exactly one
   winner per window) even before the next step.
9. **Flip `cross_pair_selection_enabled` to `True`** (requires no restart
   if the config-loader supports reload, or one more restart if it
   doesn't — either way, `validate_profile()`'s checks 2-4 now run and
   pass, since Gate A is already broad and `enabled_windows` already
   covers it — this transition cannot fail closed by construction,
   because P5 was already verified reachable in step 5's dry run). This
   is the final target state (§1).
10. **The exact point live Bridge submission becomes possible**: the
    first successful `run_cycle()` after step 8's restart (not step 9 —
    the flag makes no difference to barrier arbitration, §4.0), for a
    pair/session combination where ORB wins the opportunity-selection
    cascade and passes Risk/Compliance. Before step 8's restart, Gate A
    is still closed at the live instance and ORB cannot be `winning_
    strategy` for any pair (P1/P2) — submission is structurally
    unreachable; from step 8 onward, submission follows the pipeline's
    existing, unmodified decision path exactly as it does for the 5
    legacy strategies today.
11. **Post-activation verification** (§7): confirm boot logs show
    `valid=True` at both the step-8 and step-9 restarts, confirm the
    Bridge HTTP server is listening, confirm `run_status`/health
    diagnostics report normally, and begin the §7 observation period.
12. **Confirm no P6/P7 state was ever transiently live**: review the
    live instance's own logs/config history across steps 2-9 to confirm
    `enabled_windows` was never empty or partial at any point after Gate
    A became broad (step 8 onward) — this is the audit proof that the
    corrected sequencing was actually followed, not merely planned.

**Explicit answer to "can the Gate A source deploy itself restart the
process onto stale/old JSON?" — yes, this is a real risk, addressed by
step 8's fingerprint-reverification precondition above.** No new
production code is required to close it: the precondition is an
operator/runbook proof step (compare a file hash/mtime before and after
the redeploy), not a new validation mechanism. §8 discusses whether an
automated version would be worth adding in a future pass.

## 7. Rollback / failure handling

**§7.0 — corrected rollback semantics, superseding the original claim in
full.** The original Plan asserted "`cross_pair_selection_enabled=False`
alone is always a complete rollback." **This claim is deleted.** It is
false whenever `enabled_windows` is not simultaneously preserved
alongside a broadened Gate A (§4.0 scenario A). The corrected rule:

> **A safe rollback state is one of exactly two shapes: either Gate A is
> closed (regardless of Gate B/`enabled_windows`/flag), or Gate A remains
> broad but Gate B/`enabled_windows` retain complete coverage of it
> (regardless of the flag). There is no third safe shape.** Flipping the
> flag to `False` while leaving Gate A broad **and** clearing or
> partially reducing `enabled_windows` produces exactly §4.0 scenario A
> — unarbitrated, multi-pair execution — the opposite of a rollback.

**Rollback ordering invariant**: a config rollback must never remove
barrier coverage (`enabled_windows`/Gate B) while Gate A remains broad.
If Gate A must be closed as part of the rollback, close it (a source
redeploy) — trace-confirmed safe by `validate_profile()` check 4 failing
closed on the *next* boot attempt that re-enables the flag with Gate A
narrow, and by `check_eligibility()` immediately making ORB ineligible
for every pair once Gate A is closed, matching P1's already-safe
production-default behavior. If Gate A is to remain broad, the barrier
configuration must be left fully intact — never reduced — before or
during any other rollback action.

**Rollback A — revert Gate A to closed; Gate B/`enabled_windows` may
remain**: safe (reproduces P1/P2). This is the only rollback shape that
requires a source redeploy, but it is the most defensive: once Gate A
is closed, `check_eligibility()` makes ORB unreachable for every pair
regardless of anything else in the config.

**Rollback B — Gate A remains broad; Gate B + `enabled_windows` remain
fully populated and mutually consistent; flag set to `False`**: safe
(reproduces P4, §4.0 scenario B — arbitration still occurs, exactly one
winner per window, `call_count` matches window count, not pair count).
This is the fast rollback (config-only, no redeploy) — it removes the
flag's defense-in-depth backstop (§4.1) but does not remove the barrier
itself, since the barrier was never gated by the flag.

**Rollback C — Gate A remains broad; `enabled_windows` cleared or
reduced; flag set to `False`**: **forbidden.** Trace-confirmed
(§4.0 scenario A) to permit unarbitrated, independent, multi-pair ORB
execution — the opposite of a rollback. **An operator who "cleans up" by
clearing `enabled_windows` after already flipping the flag off, while
forgetting Gate A remains broad, produces this exact forbidden state.**
The runbook (§ below) must state this danger explicitly, not merely rely
on operator care.

| # | Failure | Handling |
|---|---|---|
| 1 | `validate_profile()` fails at a boot (any step) | Process exits (code 2) before any trading path opens — no rollback needed beyond reverting the config file to the last known-good version and restarting. |
| 2 | Live-instance config staging (step 2) succeeds but the dry run (step 5) fails | Gate A is still closed at the live instance (P2) — fully inert by construction, independent of the flag; fix the dry-run failure and re-run before proceeding to Phase E. |
| 3 | Config replacement is malformed at any step | `ConfigError` at load time, before `validate_profile()` — process refuses to start; revert config file, restart. |
| 4 | Bridge HTTP server fails to bind at any restart | Existing, pre-ADR-037 failure path (`start.py` already returns exit code 2 on bind failure) — unchanged by this Plan; revert and restart. |
| 5 | Post-activation, a Gate A pair turns out to be missing from the real `bridge.allowed_symbols` (step 4's check was performed incorrectly) | Silent no-op for that pair (§4.4) — not a crash, and does not itself enable F1 (a missing Bridge symbol removes a pair's practical reach, never adds unarbitrated reach). Remediation: add the symbol to `bridge.allowed_symbols` and restart, or perform Rollback A/B while investigating. |
| 6 | Post-activation, `superseded_opportunity_window_encountered` fires unexpectedly and repeatedly | Indicates a Gate-B/session misconfiguration or an unanticipated same-`SessionName`-distinct-anchor collision (F2 from the earlier review, confirmed non-applicable to the current 3-window plan, §0) — investigate before assuming a rollback is needed; if confirmed a real defect, perform Rollback A or B (never C). |
| 7 | **Requested rollback: set `cross_pair_selection_enabled=False`, Gate A/B/`enabled_windows` left untouched** | This is **Rollback B**, not the originally-claimed universal rollback — safe *specifically because* `enabled_windows` is left untouched. If an operator additionally clears `enabled_windows` in the same action, this becomes forbidden Rollback C. The runbook must state this distinction explicitly (§ below). |
| 8 | Partial rollback attempted (Gate B anchors removed but `enabled_windows` left referencing them, flag still `True`) | Check 1 fails at next boot (unconditional) — fail-closed, forces a complete config fix before restart succeeds; cannot leave the system in a half-rolled-back live state. |
| 9 | Rollback of the Gate A **source** change (removing the `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` entry) while the flag is still `True` in the deployed config | Check 4 fails at next boot (Gate A width `<=1`) — fail-closed; this is Rollback A, always safe regardless of what remains in `enabled_windows`. |
| 10 | Dry-run process (§5) itself crashes or hangs during observation | No production impact — `bridge_submit=None` means no live orders were ever reachable regardless of that instance's Gate A/barrier state; treat as a dry-run FAIL, fix the underlying defect, and re-run the full dry-run observation window from the start (a partial re-run does not satisfy §5's PASS criteria). |
| 11 | **(New, F1-driven)** Config rollback removes barrier coverage while Gate A remains broad at the live instance | **Forbidden — this is Rollback C.** The rollback procedure must always choose Rollback A or B; an operator must never independently decide to "just clear the new section" without first confirming Gate A's state. |
| 12 | **(New, F1-driven)** Emergency rollback needed but the operator does not know whether Gate A is currently broad at the live instance | Check the live instance's actual `titan_protocol/strategy_engine/config.py` deployment (or, more practically, its own startup logs/version) before choosing between Rollback A and B — never assume; if genuinely unknown, Rollback A (revert Gate A to closed) is the unconditionally safe choice regardless of the config's current barrier state. |

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

## 9. Adversarial activation matrix (37 scenarios — corrected, F1-driven scenarios added)

**Corrected rows are marked with a leading `[CORRECTED]`.** The original
"Risk/Bridge reachable?" column for several rows was wrong because it
inferred safety from the flag alone rather than from `enabled_windows`
coverage — the same error found in §4/§7.

| # | Scenario | Startup outcome | Risk/Bridge reachable? |
|---|---|---|---|
| 1 | Fresh deployment, no config changes at all | Boots clean, fully inert (today's default) | No (ORB never selected — Gate A closed) |
| 2 | **[CORRECTED]** Gate A source deployed, config untouched (`enabled_windows` still empty, flag `False`) | Boots clean — **no check catches this** | **Yes — reproduced (§4.0 scenario A): every Gate A pair that independently qualifies ORB reaches Risk/Bridge independently, unarbitrated. This was originally (incorrectly) marked "inert."** |
| 3 | Gate B anchors added to config, flag `False`, `enabled_windows` empty, **Gate A still closed** | Boots clean, inert (Gate A closed — ORB ineligible regardless of Gate B/`enabled_windows`) | No |
| 4 | `enabled_windows` populated (3 entries), flag `False`, **Gate A still closed** | Boots clean, inert (Gate A closed) | No |
| 5 | Flag `True`, everything else at §1 production values, Gate A source deployed | Boots clean, ORB reachable | Yes, if ORB wins cascade + passes Risk/Compliance |
| 6 | Flag `True`, `enabled_windows` empty | Check 3 fails, exit 2 | No |
| 7 | Flag `True`, Gate B anchors empty, `enabled_windows` non-empty | Check 1 fails (no matching anchor), exit 2 | No |
| 8 | Flag `True`, Gate A source not yet deployed (width 0) | Check 4 fails (`0 <= 1`), exit 2 | No |
| 9 | Flag `True`, Gate A source deployed but only 1 pair added (violates §1, hypothetical) | Check 4 fails (`1 <= 1`), exit 2 | No |
| 10 | Flag `True`, 1 Gate B anchor present, 1 `enabled_windows` entry references a *different* anchor | Check 1 fails on the mismatched entry, exit 2 | No |
| 11 | Flag `True`, anchor present, `enabled_windows` entry's `session_name` doesn't match the anchor's own `SessionName` | Check 1's session-mismatch clause fails, exit 2 | No |
| 12 | Flag `True`, 2 of 3 Gate B anchors referenced by `enabled_windows`, 3rd anchor present but unreferenced | Check 2 fails, exit 2 | No |
| 13 | Flag `True`, `enabled_windows` has an `enabled=false` entry for one of the 3 windows | Boots clean (check 2/3 only look at anchor coverage/non-emptiness, not per-window `enabled`); that specific window is structurally present but the engine's own `evaluate_window()` — re-confirm this is enforced at evaluation time via the `enabled` field, not startup, since `validate_profile()` never inspects it) — that window simply never produces a winner at runtime | Partially — 2 of 3 windows reachable |
| 14 | Gate A width exactly 2 (not the authorized 3), flag `True`, `enabled_windows` covers both | Boots clean (check 4 only requires `>1`) — a policy deviation, not a technical failure; out of this Plan's authorized §1 scope | Yes, technically — flag as a governance violation like row 16, not caught by any check |
| 15 | Gate A pair (`USDJPY`) missing from `bridge.allowed_symbols` on a given host | Boots clean (no startup check exists) — silent no-op for that pair | No, for that pair only; EURUSD/GBPUSD unaffected |
| 16 | A 4th, unauthorized Gate B anchor added by a future change without updating this Plan's authorized 3-window scope | Boots clean if internally consistent (no check limits *how many* windows), but is a policy violation, not a code failure — this Plan authorizes exactly 3, no more | Yes, but out of policy scope — flag as a governance violation, not caught by any technical gate |
| 17 | `--dry-run` flag combined with `cross_pair_selection_enabled=True` and full production values | Boots clean, ORB reachable in evaluation, `bridge_submit=None` suppresses real submission | No (by design — this is the dry-run gate itself) |
| 18 | Restart mid-session after a winner was already persisted for today's London window | `OpportunityWinnerStore`'s persisted-winner lookup returns the existing winner unconditionally (post-stale-window-correction behavior, re-confirmed) — no re-evaluation, no duplicate winner | Same as before restart (already-decided pair, if any, remains eligible for downstream Risk/Compliance) |
| 19 | Two of the three windows' anchors accidentally set to overlapping times in a hypothetical future misconfiguration | `_validate_no_overlapping_anchors` (Evidence Engine's own existing check, unconditional, independent of ADR-037's flag) fails at config-load time, before `validate_profile()` even runs | No |
| 20 | Malformed `enabled_windows` JSON (`anchor_hour_utc` as a string) | `ConfigError` at config-load time | No |
| 21 | Malformed `enabled_windows` JSON (unknown `SessionName` string) | `ConfigError` naming the invalid value and valid list | No |
| 22 | Duplicate `(anchor_hour_utc, anchor_minute_utc)` in `enabled_windows` | `ConfigError` via `OpportunitySelectionEngineConfig.__post_init__`'s existing uniqueness check | No |
| 23 | **[CORRECTED]** Operator edits only Gate B (adds 3 anchors) intending to also populate `enabled_windows`, but forgets, on a config where Gate A **has already been broadened** | Boots clean — no check catches Gate A-broad + `enabled_windows`-empty when flag is `False` | **Yes — this is scenario A/P6 again, wearing a different narrative. The flag's value is irrelevant here; only `enabled_windows` coverage matters.** |
| 24 | Operator sets the flag `True` in a config where `tie_tolerance` was also edited to a negative value | `OpportunitySelectionEngineConfig.__post_init__`'s existing `tie_tolerance < 0.0` check raises `ValueError`, surfaced as `ConfigError` at config-load time | No |
| 25 | **[CORRECTED]** Rollback B: `cross_pair_selection_enabled=False` applied while Gate A remains broad and Gate B/`enabled_windows` remain **fully populated and covering** | Boots clean; barrier still arbitrates (§4.0 scenario B) — this is the *only* circumstance under which "flag `False` + Gate A broad" is safe | **No — exactly one winner per window still reaches Risk in the ordinary, arbitrated way (not "zero reach Risk"); no unarbitrated multi-pair execution.** |
| 25b | **[NEW, F1]** Rollback C: `cross_pair_selection_enabled=False` applied while Gate A remains broad **and `enabled_windows` is simultaneously cleared or reduced** | Boots clean — no check catches this | **Yes — forbidden rollback shape (§7.0); reproduces scenario A. This is the original Plan's unrecognized "safe rollback" claim, now corrected.** |
| 26 | Dry-run (`--dry-run`) run against a config where `enabled_windows` is empty/not yet covering Gate A | Boots clean; barrier never engages for the uncovered anchors (independent of `--dry-run`) — `bridge_submit=None` still makes submission unreachable, but this proves nothing about barrier correctness and must not be mistaken for a valid dry-run proof per §5's corrected PASS criteria | No submission (dry-run flag), but also no valid arbitration proof obtained |
| 27 | Live activation (no `--dry-run`) attempted without ever having completed a passing dry-run per §5/§6 | Technically boots and trades if `validate_profile()` passes — **this is a process/governance violation, not a technical one**: §6 step 6 (Phase E) requires the dry-run to have already passed; nothing in `validate_profile()` itself can detect "was a dry-run run first," so this is enforced by the activation authorization gate, not by code | Yes, technically — which is exactly why §6's ordered procedure and §11's separate Phase E/F authorization exist |
| 28 | **[NEW, F1]** Config staged (Phase C, §6 steps 2-3) while Gate A remains closed | Boots clean, inert (P2) | No — ORB ineligible regardless of Gate B/`enabled_windows`/flag |
| 29 | **[NEW, F1]** Gate A deployed to the live instance (§6 step 8) immediately after staging, before the flag flip | Boots clean; barrier already covers every anchor (P4, §4.0 scenario B) | Exactly one winner per window, if any qualifies — arbitrated, not multiple |
| 30 | **[NEW, F1]** Gate A source deploy (§6 step 8) lands but the restart picks up a stale/reverted config (e.g. a packaging step overwrote the staged JSON with a bundled default) | Depends on the bundled default — if it has empty `enabled_windows` (matching the shipped example config), this reproduces **scenario A/P6**: broad Gate A, no barrier coverage | **Yes — exactly the danger §6 step 8's fingerprint-reverification precondition exists to catch before this step is considered complete.** |
| 31 | **[NEW, F1]** Two deployment instances (e.g. blue/green) running different generations — one with Gate A broad + full barrier coverage, one with Gate A still closed | Both boot clean independently | The broad-Gate-A instance behaves per P4/P5; the closed-Gate-A instance behaves per P1 — **the danger only arises within a single instance whose Gate A and `enabled_windows` are mismatched, not across independent instances each individually consistent** |
| 32 | **[NEW, F1]** Gate A source deploy fails (build/deploy error) after config staging (step 2) already completed | Live instance keeps running its previous binary — Gate A remains at whatever it was before the failed deploy (closed, P2, if this is the first activation attempt) | No change from the pre-attempt state — safe by construction, since a failed deploy cannot have broadened Gate A |
| 33 | **[NEW, F1]** Config deploy (step 2) fails after Gate A was already broadened by a prior (out-of-order) step | This is exactly the forbidden original ordering (Gate A before config) — **boots clean with `enabled_windows` still at its old (possibly empty) value** | **Yes — reproduces scenario A. This is precisely why §6's corrected order forbids deploying Gate A before staging the config.** |
| 34 | **[NEW, F1]** Restart occurs mid-activation, between §6 steps 8 and 9 (Gate A already deployed, flag not yet flipped) | Boots clean — this is P4, the verified-safe intermediate state | Arbitrated, one winner per window — safe, matches step 8's own stated post-condition |
| 35 | **[NEW, F1]** Rollback attempted with the operator unsure whether Gate A is currently broad at the live instance | Depends entirely on the actual state, which the operator cannot proceed without checking (§7 item 12) | Undefined until checked — **Rollback A (revert Gate A) is always the safe default choice when this is unknown** |
| 36 | **[NEW, F1]** A monitoring/regression test (§10) is added asserting scenario A's outcome, then a future code change accidentally alters `enabled_range_starts` population to also check the flag | The new test would fail, since it asserts today's actual (dangerous-if-misused) behavior — **this is intentional**: the fix for F1 is operational sequencing, not a code change, so a regression test must pin the current code behavior precisely, not assert a hoped-for future behavior | N/A — this is a test-suite integrity scenario, not a runtime scenario |
| 37 | All 5 coordinated inputs (Gate A, Gate B, `enabled_windows`, flag, Bridge symbols) at §1 production values simultaneously, reached via the corrected §6 sequence | Boots clean, fully as designed | Yes — the final target state (P5) |

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
| Fail-closed partial-state table (§4.3), flag-`True` rows only (P3, P5, P7's flag-`True` case, P9) | Existing `test_opportunity_selection_structural_readiness.py` and `validate_profile()` test coverage already exercise checks 1-4; re-confirm all pass unchanged | — |
| Bridge/Gate-A manual cross-check | — | Runbook step (§6 step 4), documented in `WINDOWS_OPERATOR_GUIDE.md` |
| DST drift is accepted, not silently wrong | — | Documented in `WINDOWS_OPERATOR_GUIDE.md` / this Plan (§8) as an operator-facing known characteristic |
| Dry-run PASS criteria (§5) | — | Operator-executed dry-run, logs + state-file snapshot retained as proof |
| Structural-boundary scope (this Plan's own diff) | `tests/titan_protocol/bridge/test_structural_boundary.py` (extended with 1 new allowed-prefix entry for this Plan's own file) | — |
| **F1 regression: broad multi-pair Gate A + `enabled_windows` empty + flag `False` (P6)** | **New test in `tests/titan_protocol/runtime/test_opportunity_selection_barrier.py`**: 3-pair `_PerPairStrategyStub` all producing `QUALIFIED` ORB snapshots, `_make_selection_engine(enabled_windows=())`, assert **all 3** outcomes are `SUBMITTED` and `risk_engine.call_count == 3` — pinning today's actual (dangerous-if-misused) behavior explicitly, so a future accidental change is caught either way (row 36 of §9) | — |
| **F1 regression: broad Gate A + `enabled_windows` partial (2 of 3 anchors covered) + flag `False`** | New test, same file: 3 pairs across 2 covered + 1 uncovered anchor; assert the covered anchor's window arbitrates to 1 winner while the uncovered pair's candidate reaches `SUBMITTED` independently — proving partial coverage is exactly as dangerous as none, for the uncovered portion | — |
| **F1 regression: broad Gate A + `enabled_windows` complete + flag `False` (P4, Rollback B)** | New test, same file: assert exactly 1 winner reaches `SUBMITTED`, others `NOT_SELECTED_OPPORTUNITY_WINDOW`, `call_count == 1` — proving the flag is provably irrelevant to barrier arbitration once coverage is complete | — |
| **F1 regression: broad Gate A + `enabled_windows` complete + flag `True` (P5)** | New test, same file: identical assertion to the row above, confirming flag `True` produces the same arbitration result (only the defense-in-depth backstop differs, §4.1) | — |
| **F1 regression: Gate A closed + Gate B/`enabled_windows` prepared (P2)** | New test, same file: Gate A empty, `enabled_windows` populated; assert no pair reaches an ORB-attributable outcome at all (only whatever non-ORB snapshot each pair was given) | — |
| **Rollback ordering: config rollback must not remove barrier coverage while Gate A remains broad (§7.0)** | New test, same file, asserting the *sequence* claim structurally: constructing the P6 state directly (as above) and confirming it reproduces the danger regardless of *how* the state was reached — this is the proof that "config rollback before Gate A rollback" is unsafe, since the resulting state is indistinguishable from any other route into P6 | Runbook procedure (§6, §7) enforces the ordering operationally; no code can distinguish "reached via rollback" from "reached via forward activation" — the corrected sequencing must be a process discipline, confirmed here to be the only available guarantee |
| `--dry-run` build proves barrier arbitration, not just non-submission (§5 PASS criteria 4-6) | Covered by the same barrier-arbitration tests above (structurally identical to what the dry run observes against real data) plus the new `--dry-run` CLI test (above) | Dry-run logs showing exactly-one-winner-per-window during the live observation window |

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
- **Phase C — production configuration preparation, corrected (§6 steps
  2-4)**: **stage** the target `titan_protocol_config.json` (Gate B/
  `enabled_windows` at §1 values, flag still `False`) **to the live
  instance itself and verify it is actually running there (P2)** —
  Gate A's source commit is prepared and reviewed but **not merged/
  deployed to the live host in this phase.** This is the corrected
  Plan's key sequencing fix: Phase C no longer merely "prepares a config
  file somewhere" — it stages and verifies it live, with Gate A still
  closed, precisely so that Phase F never needs to broaden Gate A into
  an environment lacking barrier coverage.
- **Phase D — mandatory dry run (§6 step 5)**: execute §5 in full — a
  **separate instance**, Gate A *already* broadened for that build
  specifically, Gate B/`enabled_windows`/flag=`True` matching the staged
  Phase C config, `bridge_submit=None` — for the full required
  observation window, collecting proof artifacts including the new
  barrier-arbitration/tie/incomplete-scan proofs (§5 PASS criteria 4-6).
- **Phase E — independent activation review/authorization (§6 step 6)**:
  a separate, explicit authorization — reviewing Phase D's proof
  artifacts and this Plan's own conformance — that this Plan does
  **not** itself grant.
- **Phase F — live activation (§6 steps 7-10)**: re-verify the staged
  Phase C config is unchanged, deploy Gate A's source to the **live**
  instance and restart, re-verify the config fingerprint survived the
  restart (§6 step 8's precondition), then flip the flag. **This Plan
  does NOT authorize Phase F to be performed automatically by whatever
  implementation pass follows it.** Phase F requires Phase E's separate
  authorization, obtained after this Plan's own independent review
  additionally confirms. **Gate A is broadened at the live instance
  exclusively within Phase F — never in Phase A-D** (Phase D's dry-run
  instance is a distinct, non-submitting build; broadening Gate A there
  is safe by construction, §5, and does not count as "the live
  instance").
- **Phase G — post-activation verification (§6 steps 11-12)**: confirm
  boot logs, Bridge listener, `run_status`/health diagnostics, and the
  audit review that no P6/P7 state was ever transiently live during the
  actual activation.

**The implementation pass that follows this Plan performs Phases A-C
only** (Phase C now includes live-instance config staging, which is a
config-only, Gate-A-closed, fully inert operation — safe to perform
without further authorization, matching Phase A-D's original inert-by-
construction spirit) **plus Phase D's separate dry-run build, unless a
separate, explicit authorization for Phase E/F is given.**

**Note on Phase C's operational scope (a genuine, honestly-disclosed
consequence of this correction, not glossed over):** Phase C now
requires an actual restart of the live production `start.py` process
(to stage and verify the inert config change) rather than merely editing
a file nobody deploys yet. This is a real operational action on
production infrastructure — though its *effect* is provably inert (P2)
— and should go through whatever routine deployment-restart authority
already governs ordinary config changes to this deployment today (the
same authority that would, for instance, already restart the service to
change `compliance.max_positions_per_pair`), not a new governance gate
this Plan invents. §14 records this as a process detail, not a blocker.

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
| `deployment_windows/WINDOWS_OPERATOR_GUIDE.md` | Add activation runbook section: corrected §6 sequencing, manual Bridge/Gate-A check, dry-run procedure, DST note, **and the explicit Rollback A/B/C distinction (§7.0) — must state in the runbook's own words that clearing `enabled_windows` while Gate A remains broad is forbidden, not merely implied** | §6, §7, §8, §9 |
| `tests/titan_protocol/opportunity_selection_engine/test_engine.py` or `tests/titan_protocol/runtime/test_opportunity_selection_barrier.py` | Add the F1 regression tests (§10): P6/P7/P4/P5/P2 outcomes, pinned explicitly | §10 |
| `tests/titan_protocol/bridge/test_structural_boundary.py` | Add 1 entry for `docs/plans/adr-037-production-activation-plan.md` (this Plan's own commit, this revision) | §0 |
| `docs/plans/adr-037-production-activation-plan.md` | This document (revised) | — |
| **Deliberately unchanged**: `titan_protocol/runtime/validation.py` | No new checks added — re-affirmed after re-assessment (§4.5), not merely re-asserted from the original Plan | §4.5 |
| **Deliberately unchanged**: `titan_protocol/opportunity_selection_engine/*` | Stale-window/supersession design from `aed4e65` is final for this Plan's scope | §14 |
| **Deliberately unchanged**: `titan_protocol/runtime/engine.py` | No change to `run_cycle()`'s barrier logic — F1's fix is sequencing discipline, not a code change (§4.5) | §4.5 |
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
| Bridge/Gate-A automated cross-check | Explicitly NOT required by this Plan (§4.2) — recorded as a future hardening candidate, not a blocker |
| DST-aware anchor scheduling | Product/deployment decision required if ever wanted — explicitly out of scope for this Plan (§8); current fixed-UTC behavior is accepted as-is, not a blocker to Phases A-F as specified |
| A 4th/different session window in the future | Product-policy decision required (§13) — not a blocker to activating the already-decided 3 |
| Whether Phase E/F authorization uses a written sign-off, a specific reviewer role, or another mechanism | Process detail left to whoever performs Phase E — this Plan requires only that it be separate and explicit (§11), not a specific mechanism; not safety-critical since Phase F cannot proceed without it regardless of its exact form |
| **(New, F1-driven)** Whether a future `validate_profile()` check should fail closed on broad-Gate-A + inadequate-`enabled_windows` regardless of the flag | Explicitly NOT required by this revision (§4.5) — the corrected §6 sequencing is the minimum sufficient mechanism; recorded as a genuine future hardening candidate, not a blocker to Phases A-D |
| **(New, F1-driven)** Exact mechanism for the step-8 config-fingerprint reverification (§6) — a manual hash/mtime check vs. a future automated health-check field | Implementation detail, safely resolved by precedent: a manual runbook step is sufficient for this Plan's scope (mirrors the already-accepted manual Bridge/Gate-A check, §4.2); automating it is a future hardening candidate, not required now |

No item above requires an ADR amendment.

## 15. Findings-resolution table

| Finding | Revised section(s) | Correction applied | Status |
|---|---|---|---|
| **F1** (safety-critical): the Plan treated `cross_pair_selection_enabled=False` as sufficient to make a broadened Gate A inert; false whenever `enabled_windows` is empty/inadequate | §4.0 (new corrected invariant, executable reproduction), §4.1 (flag's actual role reassessed), §4.3 (partial-state table rebuilt around barrier coverage, not the flag), §4.5 (`validate_profile()` re-assessed, no code change made), §5 (dry-run build now genuinely exercises broad Gate A safely, by construction), §6 (activation sequence re-ordered: stage config while Gate A closed, deploy Gate A only in Phase F, with an explicit stale-config precondition), §7 (rollback semantics rewritten: Rollback A/B/C, the false universal-rollback claim deleted), §9 (adversarial matrix corrected — rows 2/23/25/26 — and extended with 10 new F1-driven scenarios), §11 (Phase F is now explicitly the only phase where Gate A ever broadens at the live instance) | **Fully resolved at the Plan level.** No code change was required or made — the fix is the corrected sequencing/rollback discipline plus the executable proof that it's necessary, not a Runtime code change. |
| **F2** (non-blocking): no regression test exercised the multi-pair-Gate-A + inadequate-`enabled_windows` combination | §10 (6 new required regression tests added, explicitly pinning today's real behavior — P6/P7/P4/P5/P2 and the rollback-ordering proof) | **Resolved as a Plan requirement.** The tests themselves are not written in this pass (task instruction) — they are now a required, explicit Phase B/implementation deliverable, not merely implied. |

**No new finding surfaced during this revision that isn't already captured above.** The `validate_profile()` re-assessment (§4.5) considered adding a new code check and explicitly declined to require one — this is a documented decision, not an unresolved finding.

## 16. Fresh validation (documentation-only pass)

- `python3 -m compileall titan_protocol tests deployment_windows` — clean.
- `python3 -m unittest discover -s tests/titan_protocol/opportunity_selection_engine` — 68 tests, all green.
- `python3 -m unittest discover -s tests/titan_protocol/runtime` — 189 tests, all green.
- `python3 -m unittest tests.titan_protocol.bridge.test_structural_boundary tests.titan_protocol.runtime.test_architecture` — both green after this Plan's own file is added to the allow-list.
- `python3 -m unittest discover -s tests/deployment_windows -t .` — 162 tests, all green.
- Direct verification (in-memory, fresh): `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` still has 0 entries for `OPENING_RANGE_BREAKOUT` (Gate A untouched by this documentation-only revision); `EvidenceEngineConfig().opening_range_anchors == ()` (Gate B untouched); `OpportunitySelectionEngineConfig().cross_pair_selection_enabled is False`; `OpportunitySelectionEngineConfig().enabled_windows == ()`; `len(list(StrategyId)) == 6`; `build_default_registry(...)` still contains exactly 5 legacy strategies, ORB absent.
- **This revision's own executable reproduction** (§4.0, run via a standalone read-only script, no repo files touched): scenarios A/B/C/D all reproduced exactly as documented — scenario A (`call_count=3`, all `SUBMITTED`), B and C (`call_count=1`, single winner), D (legacy-strategy behavior, unrelated to ORB) — confirming this revision's central correction is proven, not asserted.
- `git status` — clean except this one revised documentation file (plus the one-line `test_structural_boundary.py` allow-list addition made alongside it, unchanged from the drafting pass). No Gate A, Gate B, `enabled_windows`, or `cross_pair_selection_enabled` value was written anywhere in the repository during this revision.

## 17. Commit / disposition

This diff is confined to: the revised Plan document, and the one-line
addition to `tests/titan_protocol/bridge/test_structural_boundary.py`'s
`allowed_prefixes` tuple required for it to pass (unchanged from the
original drafting pass — this revision adds no new files). No production
configuration, source constant, or activation flag was written by this
pass.

---

**This pass authorizes no production activation.** Even though this Plan
is being finalized as implementation-ready (again, after correction),
Gate A/B population, `cross_pair_selection_enabled=True`, and live
Bridge submission remain prohibited until: (1) an implementation pass
builds Phases A-C (config-loading code, tests, and live-instance config
staging with Gate A still closed) plus Phase D's separate dry-run build,
exactly as specified here; (2) the mandatory dry-run (§5) passes against
the real target deployment; and (3) Phase E's separate, explicit
activation authorization is obtained. This Plan's own finalization is not that
authorization.

**ADR-037 PRODUCTION ACTIVATION PLAN REVISED — READY FOR INDEPENDENT PLAN RE-REVIEW**
