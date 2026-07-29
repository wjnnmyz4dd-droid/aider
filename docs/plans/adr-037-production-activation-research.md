# ADR-037 — Production Activation Research

Status: **Research only.** No production configuration modified, no Gate
A/B activation performed, `cross_pair_selection_enabled` left `False`,
no legacy-strategy retirement, no runner-up fallback, no ADR-035 Phase 5
work. This document identifies the minimum safe production-activation
policy for ADR-037 without inventing deployment values it is not
authorized to choose.

Depends on: ADR-037 (Accepted) + Amendment 1 (Accepted, Persistence
Semantics Correction); ADR-031 Amendment 1 (Accepted); ADR-036 (Accepted)
+ Amendment 1 (Accepted, operational-readiness precondition);
`docs/plans/adr-037-ranking-tie-session-policy-decision.md` (product-
policy gate closed); the ADR-037 implementation at commit `aed4e65`
(independently re-reviewed conformant — see below).

## 0. Repository / governance baseline (re-verified fresh for this pass)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `aed4e65`, clean
  tree, in sync with upstream, before and after this Research pass.
- ADR-037 implementation independently re-reviewed CONFORMS —
  GOVERNANCE GATE CLOSED at `aed4e65` (prior session). Not re-litigated
  here; treated as settled input.
- Gate A: `OPENING_RANGE_BREAKOUT` absent from `DEFAULT_APPROVED_PAIRS_BY_
  STRATEGY` (`titan_protocol/strategy_engine/config.py`) — closed.
- Gate B: `EvidenceEngineConfig.opening_range_anchors` defaults to `()`
  and the shipped example config (`deployment_windows/config/
  titan_protocol_config.example.json:77`) sets it to `[]` — empty.
- Production wiring: `OpportunitySelectionEngineConfig()` constructed
  with bare defaults in `deployment_windows/start.py` —
  `cross_pair_selection_enabled=False`, `enabled_windows=()`.
- 6 `StrategyId` members; legacy registry (`build_default_registry()`)
  contains exactly the 5 legacy strategies, ORB absent.
- Fresh validation: `compileall` clean; `opportunity_selection_engine`
  (68), `runtime` (189), `deployment_windows` (162, run with `-t .`) all
  green.

## 1. Gate A research — production pair universe for ORB

**What exists today:**

- `StrategyEngineConfig.DEFAULT_APPROVED_PAIRS_BY_STRATEGY` gives each of
  the 5 legacy strategies 4–7 pairs (majors plus a few crosses), e.g.
  `LIQUIDITY_SWEEP_MSS`/`BOS_FVG`: `EURUSD, GBPUSD, USDJPY, USDCHF,
  AUDUSD, USDCAD, NZDUSD` (7 pairs). No entry exists for
  `OPENING_RANGE_BREAKOUT` — Gate A is not merely narrow, it is absent.
- The actual per-cycle evaluated universe is **not** Gate A alone:
  `deployment_windows/config_loader.py::build_trading_profile()` forces
  `profile.allowed_pairs = settings.bridge_config.allowed_symbols` and
  fails closed if any profile pair isn't Bridge-accepted. The shipped
  example config's `bridge.allowed_symbols` is exactly the same 7 majors
  (`EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD`). ADR-037 §7
  itself frames the tracked universe as `Gate A ∩ allowed_pairs`
  (confirmed in `run_cycle()`'s `tracked_pairs` computation) — so
  **whatever Gate A eventually names for ORB is further intersected with
  the Bridge's own configured symbol list**; naming a pair for ORB that
  isn't also in `bridge.allowed_symbols` would silently exclude it from
  ORB's actual tracked/candidate universe (not a startup failure, since
  Gate A's own eligibility list and Bridge's symbol list are independent
  fields with no cross-validation between them today — a real, minor gap
  worth flagging, not one this Research invents a fix for).
- `orb_breakout.py::qualify()`'s own gates (spread `<= orb_max_spread_pips`,
  liquidity `>= orb_min_liquidity_score`, holiday, news blackout, ATR-
  relative range-quality) are pair-agnostic thresholds applied identically
  to whichever pairs are named — they do not themselves argue for
  specific pairs, only that any named pair must realistically be able to
  satisfy them (i.e., not an illiquid/wide-spread instrument).
- ADR-037's own ranking policy is pair-scale-independent (`score` is
  bounded `[0,100]`, per the Decision document §2/§7) — the ranking rule
  imposes no constraint on Gate A's composition, and Gate A's width has
  no dependency back onto ranking correctness. The only load-bearing
  dependency runs the other direction: **ADR-037 §11 item 2 makes a
  single-pair Gate A a no-op** ("a single-pair Gate A would make this
  ADR's mechanism a no-op — nothing to select between"), and the
  implemented `validate_profile()` check 4 (independently re-verified,
  `titan_protocol/runtime/validation.py`) already fails closed on exactly
  this: `cross_pair_selection_enabled=True` with `len(orb_pairs) <= 1` is
  rejected at startup. **A small initial Gate A set (e.g. 2–4 pairs) is
  therefore structurally sufficient** — nothing in the architecture
  rewards or requires a broad set beyond "more than one," and a small set
  is the more conservative, more easily-audited choice, consistent with
  `CLAUDE.md` §6 (smallest defensible policy) and ADR-036 Amendment 1's
  own posture (structural readiness, not maximal breadth).
- No pair needs exclusion for a **structural** reason beyond the above
  (must be `>1` pair, and must be present in `bridge.allowed_symbols` to
  actually be evaluated). No repository evidence excludes any specific
  pair from ORB eligibility on structural grounds.

**What is not resolved by any repository evidence:** the exact pair(s).
ADR-036 Amendment 1 explicitly lists this as deferred future Plan work
("the exact pair(s) to grant ORB eligibility for... each a future Plan's
responsibility"); the Decision document §7 restates the same ("No exact
production Gate A pair list is chosen or required by this decision...
explicitly deferred to the ADR-036/ADR-037 implementation Plan"). No
backtesting/forward-testing evidence (Validation Engine outputs,
Research Engine attribution reports) exists in the repository naming
specific pairs as ORB-suitable — `18.B` in ADR-035 itself says exact
defaults "are proposed, reasonable starting points, not empirically
validated — real backtesting/forward-testing... should inform final
defaults before Phase 5."

**Conclusion:** exact Gate A pair selection **requires a separate
product/deployment decision** — it is not uniquely determined by
existing evidence. The only two governed constraints on that future
decision are: (a) more than one pair if `cross_pair_selection_enabled`
will be `True` (already enforced), and (b) every named pair must also be
added to `bridge.allowed_symbols` or it is silently inert.

## 2. Gate B research — anchor hour/minute values for the three initial windows

**What is already settled (Accepted governance):** the Decision document
(§5, revised after independent review) settles the *session identity*
of the initial production policy as three windows —
`SessionName.LONDON`, `SessionName.LONDON_NEW_YORK_OVERLAP`,
`SessionName.EARLY_NEW_YORK` — each independently keyed, no two sharing
a `SessionName` (verified: `list(SessionName)` has 6 members total;
these three are pairwise distinct labels). This settles *which*
sessions, not *when* their opening ranges anchor in clock time.

**What is explicitly not settled anywhere:** the Decision document's own
§5 final paragraph and §8 state, verbatim, that "no anchor hour/minute
values are chosen" and that this is "future deployment-profile content."
ADR-037 Amendment 1 §7 lists "the initial production policy of London +
London–New York Overlap + Early New York, or any other exact
session/pair/anchor value" as explicitly unauthorized by that amendment,
pointing at the Decision document as the place session identity (not
clock values) was resolved.

**A tempting but explicitly-rejected shortcut, checked directly:**
`EvidenceEngineConfig` already carries real, Accepted (ADR-024) numeric
hour fields for session **classification** — `london_session_start_hour
= 7`, `new_york_session_start_hour = 12`, `london_new_york_overlap_
start_hour = 12`, `london_new_york_overlap_end_hour = 16`, `early_new_
york_end_hour = 18`. These look like they could suggest anchor values
(London ≈ hour 7, Overlap ≈ hour 12, Early NY ≈ hour 16), but the
Decision document (§5) explicitly warns against this exact inference:
these fields describe *session classification* boundaries for
Evidence/MI scoring — "a separate mechanism from Gate B's
`opening_range_anchors`... and are not themselves opening-range anchor
values, so they do not by themselves settle an anchor choice either."
This Research does not invent an anchor choice from them, per that
explicit instruction and per this task's own "do not invent clock
values" constraint.

**Feasibility, not choice (re-verified):**
`_validate_no_overlapping_anchors` (`evidence_engine/config.py`) rejects
only anchors whose *actual* `[range_start, range_end)` windows collide —
not anchors whose parent sessions' broader hour ranges overlap. Since
each of the three windows' opening range would naturally anchor near
that session's own start, configuring all three as simultaneously valid,
non-colliding Gate B anchors remains expected to be feasible — this is a
feasibility observation, independently re-confirmed by reading the
validator, not a resolution of the values themselves.

**Conclusion:** Gate B anchor hour/minute values for all three windows
**require their own separate deployment-profile decision** — repository
evidence does not uniquely establish them, and the one document that
comes closest to the question (the Decision document) explicitly
declines to answer it and names the classification-hour fields as a
non-authoritative false lead.

## 3. Activation mechanics — full trace of what must change

Traced end-to-end from the current inert state:

| Step | What changes | Current support | Gap |
|---|---|---|---|
| 1 | Gate A: add an `OPENING_RANGE_BREAKOUT` entry to `approved_pairs_by_strategy` | `StrategyEngineConfig` field already exists; `config_loader.py` reads `strategy_engine` overrides from JSON | Needs exact pairs (§1) |
| 2 | Gate B: add ≥1 `opening_range_anchors` entries | `EvidenceEngineConfig` field + full JSON-loading path already exist (`config_loader.py:420-443`, confirmed) | Needs exact clock values (§2) |
| 3 | `OpportunitySelectionEngineConfig.enabled_windows` populated to match Gate B | Dataclass field exists (`EnabledOpportunityWindow(session_name, anchor_hour_utc, anchor_minute_utc, enabled)`) | **No JSON-config-loading path exists at all** — `deployment_windows/start.py:1143` hardcodes `OpportunitySelectionEngineConfig()` with bare defaults, never reading from `settings`. This is a **code change**, not a config-value edit — `config_loader.py`'s `Settings`/`DeploymentSettings` would need a new field and `start.py` would need to consume it. |
| 4 | `cross_pair_selection_enabled=True` | Same field, same gap as step 3 | Same code-change requirement as step 3 |
| 5 | `validate_profile()` startup checks | Already implemented and independently re-verified (4 checks: anchor-reference validity, anchor-coverage when active, non-empty `enabled_windows` when active, Gate A width `>1` when active) | None — ready as-is, requires no further work |
| 6 | Deployment wiring/config ownership | `start.py` already passes `evidence_config`/`opportunity_selection_config` into `validate_profile()` and constructs `OpportunitySelectionEngine` | Only the loading gap in steps 3–4 |
| 7 | Rollback path | Setting `cross_pair_selection_enabled=False` (or emptying `enabled_windows`) reverts to the fully-verified inert/legacy-coexistence behavior — no code rollback needed, a config-only revert, and `validate_profile()`'s checks 2–4 do not even run when the flag is `False` | None |

**Smallest atomic activation sequence:** Gate A, Gate B, and the flag
must land **together** to preserve fail-closed startup semantics.
Reasoning, independently re-derived from `validate_profile()`'s own
logic: check 4 (Gate A width) and checks 2–3 (anchor coverage,
non-empty `enabled_windows`) only fire when `cross_pair_selection_
enabled=True` — so populating Gate A/B alone, with the flag still
`False`, is safe but produces zero behavior change (still fully inert,
per ADR-036 Amendment 1's own condition 3's "narrow/fixed Gate A route"
framing — populating Gate A/B without flipping the flag is exactly the
inert configuration that route describes). Flipping the flag alone,
before Gate A/B are populated, is caught and refused by the same
checks (empty `enabled_windows`, Gate A width `<= 1`) — fail-closed, not
silently unsafe. **The only order that is both safe and produces the
intended live behavior is: populate Gate A, populate Gate B, populate
`enabled_windows`, then set the flag — with steps 3–4's code gap
(above) closed first**, since there is currently no way to set steps 3–4
via configuration alone.

## 4. Pre-activation safety

**Proof required before activation:** a realistic end-to-end test run
with non-empty Gate A (≥2 pairs), non-empty Gate B (the eventual anchor
values), `enabled_windows` populated to match, and
`cross_pair_selection_enabled=True` — exercising the full production
path (`run_cycle()` → classification → barrier → OSE → winner-store →
winner-only `_run_back_half` → Risk) with realistic post-formation
timing (the exact class of test added in the stale-window correction,
`aed4e65`) and with **at least one scenario per adversarial row** already
catalogued in ADR-037 §15 and the Decision document §9 (score-only
winner, tie, incomplete scan, selector failure, multiple windows,
anchor-not-enabled suppression). Every one of these already has direct
unit/integration test coverage using synthetic fixtures; what does not
yet exist is a run using the **actual chosen production values** (real
pairs, real anchors) once those are chosen — that is Plan/pre-activation
work, not something this Research can perform without the values.

**Shadow/dry-run capability — researched, not invented:** two genuinely
different capabilities already exist in the architecture, and this
Research distinguishes them:

- **Validation Engine's `shadow_trading.py`** (`run_shadow_comparison()`)
  is a **post-hoc, offline comparison** of two already-completed
  `ConfigurationRun` result sets (production vs. candidate), reusing
  `research_engine.effectiveness.compare_buckets`. It never participates
  in live execution (Runtime's own docstring: "Validation Engine is
  never imported here"). This is backtesting/replay-comparison, not a
  live dry-run.
- **`RuntimeOrchestrator(bridge_submit=None)`** is an already-existing,
  already-used construction pattern (confirmed in multiple existing
  tests) that lets the **entire** production pipeline — Evidence → MI →
  Strategy → the ADR-037 barrier/OSE/winner-store → Risk → Compliance —
  execute for real, against live market data, while guaranteeing zero
  command ever reaches the Bridge (the `_run_back_half` code path that
  would build/submit a `TradeCommand` is skipped entirely when
  `bridge_submit is None`; the reservation is released instead). This is
  a genuine, already-supported live dry-run for the ADR-037 mechanism
  specifically — no new architecture is required to use it. One caveat
  worth flagging (not fixing here): the resulting `RuntimeAuditRecord`
  still reports `CycleOutcome.SUBMITTED` for what would have been a live
  submission, which could read as "a trade happened" to an operator
  glancing at logs without knowing `bridge_submit` was `None` — a UX/
  observability nuance for whoever designs the dry-run runbook, not an
  architecture gap.

**F2 (spurious `superseded_opportunity_window_encountered`) applicability
to the planned three-window configuration:** re-checked directly — F2's
trigger condition is two *distinct* anchors sharing one `SessionName`.
The three currently-planned windows (`LONDON`, `LONDON_NEW_YORK_OVERLAP`,
`EARLY_NEW_YORK`) are three **distinct** `SessionName` values, verified
against the full `SessionName` enum (6 members, no duplication among the
three). **F2 cannot fire under this specific three-window plan** and is
therefore **not a pre-activation prerequisite** for it. It would become
relevant only if a future configuration ever introduced two anchors
under the same `SessionName` (e.g., splitting "early London" and "late
London" both labeled `LONDON`) — worth correcting before that
configuration is ever attempted, but not before this one.

**A distinct, real gap this Research surfaces (not previously flagged):**
`EvidenceEngineConfig.__post_init__` validates weight-sum, `min_bars`,
anchor non-overlap, and duration-feasibility — but never validates that
`start_hour_utc ∈ [0,23]` or `start_minute_utc ∈ [0,59]` for any
configured anchor. This is the already-named "ADR-035 Phase 5 anchor
hour/minute range-validation residual risk" (confirmed present in
`docs/plans/adr-035-phase6-full-suite-validation.md`, explicitly
excluded from that Plan's scope). A malformed anchor value would not be
caught at startup — it would raise inside `datetime.replace()` at
runtime, caught by Runtime's own front-half exception handling
(`CycleOutcome.FAILED`, not a crash), producing per-cycle failure noise
for the affected pair indefinitely rather than a clear boot-time error.
This **does not block activation** for a correctly-entered configuration
and is **not itself a capital-preservation gap** (fails closed either
way), but it is a concrete reason the pre-activation end-to-end test
(above) matters: a typo'd anchor value would only surface as an
unexplained sustained `FAILED` rate, not a refusal to boot.

## 5. Governance separation

- **ADR-036 legacy-strategy retirement:** independently re-checked —
  does **not** block ADR-037 activation. ADR-037 §5.G explicitly designs
  for coexistence ("before ADR-036 retirement is complete, the registry
  may still contain the five legacy strategies... this ADR's mechanism
  is additive"); a legacy-strategy winner always takes the unmodified
  non-participating path regardless of ADR-037's activation state.
  Conversely, ADR-037 activation is not itself sufficient for ADR-036
  retirement — ADR-036 Amendment 1's own conditions 1–3 (Gate A lifted,
  Gate B lifted, fail-closed startup check) happen to overlap with
  ADR-037 activation's own Gate A/B population, but Amendment 1's
  conditions are about when retirement may be considered *complete*, a
  separate, later, independent decision.
- **Runner-up fallback:** already settled as *not adopted* for v1 by
  ADR-037 §10 (unaltered) and the Decision document §3 — this is a
  closed decision, not an open blocker. Absence of a runner-up policy
  does not block activation; it is the current, correct, intended
  behavior ("no trade that cycle" on downstream rejection).
- **ADR-035 Phase 5 anchor hour/minute validation follow-up:** does
  **not** block activation for a correctly-configured deployment (§4,
  above) — it is a defense-in-depth gap for malformed input, not a
  functional dependency of ADR-037's own mechanism.

None of the three actually blocks ADR-037 activation; all three are
correctly kept as separate governance tracks.

## 6. Adversarial activation scenarios

| # | Scenario | Outcome under current architecture |
|---|---|---|
| 1 | Operator populates Gate A/B and `enabled_windows` but forgets to flip `cross_pair_selection_enabled` | Fully inert — `validate_profile()`'s checks 2–4 never run; ORB candidates take the ordinary non-participating path, exactly as today. Safe, but not the intended live behavior. |
| 2 | Operator flips the flag before Gate A/B are populated | `validate_profile()` fails closed (`enabled_windows` empty check, or Gate A width `<= 1` check) — refuses to boot. |
| 3 | Operator names an ORB pair not in `bridge.allowed_symbols` | Silently excluded from ORB's tracked/candidate universe (Gate A ∩ allowed_pairs) — no startup error, since Gate A and `bridge.allowed_symbols` are validated independently, not cross-checked against each other. A real, minor gap; does not cause unsafe behavior (the pair simply never becomes an ORB candidate), but could silently produce "activated but doing nothing for pair X" confusion. |
| 4 | Operator enters a malformed anchor hour/minute (typo) | Not caught at startup (§4's residual-risk finding) — surfaces as a sustained per-cycle `FAILED` outcome for the affected pair only, at runtime. Fails closed, but not fail-*fast*. |
| 5 | Two of the three initial windows configured with overlapping opening-range clock windows | `_validate_no_overlapping_anchors` fails closed at startup — already covered, independently re-verified. |
| 6 | Deployment activates ADR-037 while ADR-036 retirement has not happened | Explicitly supported coexistence state (§5.G) — legacy strategies and ORB candidates coexist correctly, independently re-verified via the barrier tests' own legacy-winner-unaffected scenarios. |
| 7 | A future deployment adds a second anchor sharing a `SessionName` with one of the three initial windows | Triggers F2 (spurious `superseded_opportunity_window_encountered` log) — cosmetic only, does not affect winner selection/Risk routing (independently re-verified in the prior conformance re-review), but should be corrected before this specific configuration is attempted. |

## 7. Unresolved decisions (explicitly left open by this Research)

- The exact Gate A production pair list (§1) — product/deployment
  decision, not resolved here.
- The exact Gate B anchor hour/minute values for London, Overlap, and
  Early New York (§2) — product/deployment decision, not resolved here.
- The `enabled_windows`/`cross_pair_selection_enabled` JSON-config-
  loading gap (§3, steps 3–4) — an implementation task for a future Plan,
  not a product-policy question, but a genuine prerequisite before Gate
  A/B values alone are sufficient to activate ADR-037 from the
  deployment config file.
- Whether/when to correct F2 — recommended before any deployment
  introduces two same-`SessionName` anchors, not before the currently-
  planned three-window rollout.
- Whether/how to add a Gate-A/`bridge.allowed_symbols` cross-check
  (scenario 3, above) and an anchor hour/minute range check (the Phase 5
  residual risk) — both legitimate future hardening candidates, neither
  a blocker, both out of this Research's authority to implement.

## 8. Recommended next governance vehicle

A dedicated **ADR-037 Production Activation Plan** (its own RPI
Plan → independent Plan review → Implement cycle), scoped to exactly:
(a) the config-loading code change for `enabled_windows`/
`cross_pair_selection_enabled` (§3, steps 3–4); (b) closing on the exact
Gate A pair list and Gate B anchor clock values, each as its own
product-policy sub-decision (structurally identical to how the Decision
document resolved ranking/tie/session-identity, but for these two
remaining open values); (c) the pre-activation end-to-end proof (§4)
using the values chosen in (b); (d) an explicit rollback runbook entry
(trivial per §3 step 7, but worth documenting). This Plan should not
bundle ADR-036 retirement, runner-up fallback, or ADR-035 Phase 5 work —
confirmed independent in §5.

## 9. Explicit authorization boundaries (restated)

This document authorizes nothing. It does not authorize: Gate A or Gate
B activation; any exact production pair, anchor, or clock value;
`cross_pair_selection_enabled=True`; the `enabled_windows` config-loading
code change; legacy-strategy retirement; runner-up fallback; ADR-035
Phase 5 work. Production activation remains unauthorized regardless of
this Research's disposition.

## 10. Validation (read-only, this pass)

`compileall` clean; `opportunity_selection_engine` (68), `runtime`
(189), `deployment_windows` (162, `-t .`) all green; Gate A closed; Gate
B empty; `cross_pair_selection_enabled=False`; 6 `StrategyId` members;
legacy registry intact (5 strategies, ORB absent); clean tree before,
during, and after this Research.

---

*This document is a Research artifact. It authorizes no implementation,
no configuration change, and no activation. Exact Gate A pairs and Gate
B anchor clock values are not uniquely determined by existing repository
evidence and require their own product/deployment decision before an
Activation Plan can be finalized.*
