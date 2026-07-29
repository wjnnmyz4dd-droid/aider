# Policy Decision — ADR-037 Production Activation

Status: **Partial policy decision.** The activation-mechanics and
pre-activation-process questions (§C, §D below) are decided by this
document. **The two principal value decisions — the exact Gate A pair
list and the exact Gate B anchor hour/minute values — are not resolved
here.** Independent re-verification of every authoritative source this
repository contains (ADR-036 + Amendment 1, ADR-037 + Amendment 1, the
ranking/tie/session-policy Decision document, ADR-035, and Research
Engine's own pair-intelligence module) confirms neither value is
uniquely determined by existing evidence — each requires a genuine,
irreducible product choice this document does not manufacture. This
document amends no ADR, implements no code, and does not authorize
production activation.

Depends on: ADR-037 (Accepted, base + Amendment 1); ADR-031 Amendment 1
(Accepted); ADR-036 (Accepted, base + Amendment 1);
`docs/plans/adr-037-ranking-tie-session-policy-decision.md` (product-
policy gate closed for ranking/tie/session-identity); the ADR-037
implementation, independently re-reviewed conformant through `aed4e65`;
`docs/plans/adr-037-production-activation-research.md` (the Research
artifact this document closes what it can of).

## 0. Repository / governance baseline (re-verified fresh for this pass)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `ea53932`, clean
  tree, in sync with upstream, before this pass began.
- ADR-037 base: Accepted (status header, re-read directly). Amendment 1
  (Persistence Semantics Correction): Accepted 2026-07-29 (re-read
  directly).
- ADR-037 implementation conformant through `aed4e65` and the
  subsequent reviewed stale-window correction — re-confirmed by direct
  source read (below), not by trusting the prior session's own report.
- Gate A: `OPENING_RANGE_BREAKOUT` absent from `DEFAULT_APPROVED_PAIRS_
  BY_STRATEGY` — closed.
- Gate B: `EvidenceEngineConfig.opening_range_anchors` defaults to `()`;
  shipped example config sets it to `[]` — empty.
- Production wiring: `OpportunitySelectionEngineConfig()` constructed
  with bare defaults in `deployment_windows/start.py` —
  `cross_pair_selection_enabled=False`, `enabled_windows=()`.
- 6 `StrategyId` members; `build_default_registry()` contains exactly
  the 5 legacy strategies, ORB absent.

## A. Gate A — initial production ORB pair universe

**Architectural eligibility vs. deployment availability vs. trading-
policy preference, explicitly separated:**

- **Architectural eligibility** (what the code will accept without
  complaint): any pair string matching `_PAIR_PATTERN` (`^[A-Z]{6}$`,
  `titan_protocol/runtime/validation.py`) named in
  `approved_pairs_by_strategy` for `OPENING_RANGE_BREAKOUT`. No
  structural restriction beyond count (`>1` when
  `cross_pair_selection_enabled=True`, already enforced by
  `validate_profile()` check 4, independently re-verified in
  `titan_protocol/runtime/validation.py`).
- **Deployment availability** (what could actually trade even if named):
  the pair must also be in `bridge.allowed_symbols` — the shipped
  example config's value is exactly `EURUSD, GBPUSD, USDJPY, USDCHF,
  AUDUSD, USDCAD, NZDUSD` (re-read directly from
  `deployment_windows/config/titan_protocol_config.example.json:27` and
  `deployment_windows/config_loader.py::build_trading_profile()`, which
  forces `profile.allowed_pairs` to exactly this set and fails closed on
  any mismatch). Any Gate A pair outside this set is silently inert
  (Research §1, re-confirmed) until the deployment's own
  `bridge.allowed_symbols` is also widened — a separate deployment
  action, not a Gate A decision alone.
- **Trading-policy preference** (which of the architecturally-eligible,
  deployment-available pairs *should* be chosen): this is the
  irreducible product choice. No repository evidence resolves it.

**Evidence searched and found insufficient to uniquely justify a
specific list:**

- `titan_protocol/research_engine/pair_intelligence.py::rank_pairs()`
  takes `trades: Sequence[ClosedTrade]` as its only data source —
  independently re-read: it is a **pure function of historical closed
  trades**, with zero hardcoded pair preference of its own. Since Gate A
  has never had an ORB entry, no `ClosedTrade` attributable to ORB
  exists anywhere in this repository's history. This function
  **cannot** and does not produce any ORB-specific pair ranking today —
  confirmed by its own signature, not merely by absence of a report.
- ADR-035 §18.B item 4 (re-read directly) itself proposes "empty by
  default (safest, forces deliberate operator choice)" as its own
  *recommendation*, explicitly not an empirically-validated pair list —
  the ADR that defined ORB's own thresholds does not resolve this
  question either.
- ADR-036 Amendment 1 (re-read directly) lists "the exact pair(s) to
  grant ORB eligibility for" as explicitly deferred future Plan work.
- The Decision document §7 (re-read directly): "No exact production
  Gate A pair list is chosen or required by this decision... The exact
  production pair list remains unresolved, explicitly deferred to the
  ADR-036/ADR-037 implementation Plan."
- `orb_breakout.py::qualify()`'s own gates (spread, liquidity, holiday,
  news, ATR-relative range quality) are pair-agnostic thresholds — they
  constrain *how a named pair must behave to qualify*, not *which pairs
  should be named*.

**Conclusion — Gate A: USER DECISION REQUIRED.** The irreducible choice
remaining is exactly: **which specific pairs (at minimum 2, all already
present in, or to be added to, `bridge.allowed_symbols`) should
initially be granted ORB eligibility.** This document does not
manufacture a ranking, threshold, or preference to answer it — no such
evidence exists to manufacture it from.

## B. Gate B — anchor hour/minute values for the three initial windows

**Session identity vs. clock-time realization, explicitly separated:**
the Decision document §5 (re-read directly, Accepted product policy)
already settles *which* three sessions are initial production policy —
`SessionName.LONDON`, `SessionName.LONDON_NEW_YORK_OVERLAP`,
`SessionName.EARLY_NEW_YORK` — on the evidentiary basis of
`MarketIntelligenceConfig.preferred_sessions` and
`evidence_engine/session.py::SESSION_QUALITY_SCORES`, both independently
re-read and confirmed unchanged. **This document does not reopen that
decision.** What remains is *when*, in UTC clock time, each window's
Gate B anchor (`opening_range_anchors` entry: `(SessionName, hour,
minute)`) should sit.

**The tempting shortcut, checked again and confirmed still rejected:**
`EvidenceEngineConfig`'s session-*classification* hour fields
(`london_session_start_hour=7`, `london_new_york_overlap_start_hour=12`,
`london_new_york_overlap_end_hour=16`, `early_new_york_end_hour=18`, all
independently re-read from `evidence_engine/config.py`) are Accepted
(ADR-024) values, but they govern a **different mechanism** — bucketing
a bar's timestamp into a `SessionName` label for Evidence/MI *scoring*,
never referenced by `compute_opening_ranges()` or any Gate B code path
(independently re-verified: `opening_range.py` takes only
`opening_range_anchors`, never any `*_session_start_hour`/`*_end_hour`
field). The ranking/tie/session-policy Decision document's own §5
explicitly names this exact inference as illegitimate ("do not by
themselves settle an anchor choice either"). This document does not
perform that inference.

**DST/timezone implications — resolved by existing, already-Accepted
repository-wide convention, not a new decision:** independently traced
three separate precedents, all consistent: ADR-035 §3/§15 (re-read
directly) states ORB's own clock-anchor field is "explicitly NOT
DST-aware... An operator updates [the UTC anchor hour] twice a year if
their broker's own UTC offset changes with DST" — an already-Accepted,
already-shipped limitation (`docs/plans/adr-035-phase6-full-suite-
validation.md` confirms this was deliberately left untested, "documented
as an operator responsibility," not a code gap). `titan_protocol/
compliance_state_store/config.py`'s `daily_reset_hour_utc` field
carries the identical documented convention verbatim ("this store...
does not attempt DST-aware timezone conversion; operators... must
update this value when that offset changes"). `titan_protocol/runtime/
models.py`'s `TradingProfile.trading_window` is documented the same way
("No timezone/DST logic — operator-configured, in UTC"). **Gate B's
`opening_range_anchors` is the same shape of field (a fixed UTC
hour/minute) governed by the same already-Accepted, repository-wide
convention** — DST is an **operator runbook responsibility** (update the
UTC anchor hour/minute twice yearly if the broker's own local-time
session boundaries shift with DST), not an unresolved architectural
question this document must invent an answer to.

**Feasibility, re-confirmed:** `_validate_no_overlapping_anchors`
(`evidence_engine/config.py`, re-read directly) rejects only anchors
whose actual `[range_start, range_end)` windows collide in clock time —
not anchors whose parent sessions' broader hour ranges overlap.
Configuring three anchors, one near each session's own start, remains
expected to be feasible without contradiction — a feasibility fact, not
a value.

**No terminal opportunity-window boundary is invented by this
document:** consistent with Amendment 1 §2 (already-Accepted,
unaltered by the stale-window correction at `aed4e65`), each anchor
remains an ordinary, calendar-day-recurring `(SessionName, hour, minute)`
entry with no "closing time" concept beyond its own formation duration —
this document adds no new lifecycle semantics.

**Evidence searched and found insufficient to uniquely justify specific
hour/minute values:** the Decision document §5/§8 (re-read directly,
verbatim): "no anchor hour/minute values are chosen... future
deployment-profile content." ADR-037 Amendment 1 §7 (re-read directly)
lists "any other exact session/pair/anchor value" as explicitly
unauthorized by that amendment. No other Accepted document in the
repository assigns UTC clock values to Gate B anchors for these three
sessions.

**Conclusion — Gate B: USER DECISION REQUIRED.** The irreducible choice
remaining is exactly: **the UTC anchor hour/minute for each of London,
London–New York Overlap, and Early New York's opening range**, subject
only to the already-governed non-overlap constraint (feasible, not
chosen, by this document) and the already-Accepted DST-is-an-operator-
responsibility convention (inherited, not invented, by this document).

## C. Activation/config policy — decided

These are process/architecture-ownership questions, not pair/anchor
value choices, and are resolved here on existing precedent:

**C1. Where production values for `enabled_windows`/`cross_pair_
selection_enabled` should originate — DECIDED: the same deployment JSON
config file that already owns Gate A/B (`titan_protocol_config.json`),
under its own dedicated section, loaded through `config_loader.py`
exactly as `evidence_engine`/`strategy_engine` sections already are
today — never a hardcoded value in `start.py`, an environment variable,
or a second config file.** Grounds: the Decision document §10
(independently re-read, itself independently reviewed and found sound)
already recommends the Opportunity Selection Engine own its own config
class, following the identical per-engine-owns-its-config pattern every
other pipeline-stage engine already uses; `config_loader.py` already
demonstrates the exact loading pattern needed (`opening_range_anchors`'s
own JSON-array-to-tuple loading, re-read directly at
`config_loader.py:420-443`) — this is architecture-ownership precedent
already established, not a new design. This decision does not specify
the exact JSON key name, dataclass field layout, or `Settings`
plumbing — those remain Plan/implementation work.

**C2. Whether activation must be atomic/coordinated across Gate A, Gate
B, `enabled_windows`, the selection flag, and Bridge symbol
availability — DECIDED: yes, all five must be set together in one
deployment change, verified by one clean `validate_profile()` pass at
boot before the deployment is considered live.** Grounds: independently
re-derived from `validate_profile()`'s own logic (re-read directly) —
checks 2–4 (anchor coverage, non-empty `enabled_windows`, Gate A width)
fire only when `cross_pair_selection_enabled=True`, so any deployment
sequencing that sets the flag before Gate A/B/`enabled_windows` are
fully populated is already caught and refused at boot (fail-closed, not
merely recommended). Bridge-symbol availability is **not** yet
cross-validated in code (Research §1's real, minor gap, re-confirmed) —
this document's policy accordingly **requires operators to manually
verify** every Gate A ORB pair is present in `bridge.allowed_symbols`
as a pre-activation runbook step, until a future hardening item closes
that gap in code.

**C3. Required fail-closed behavior for partial/mismatched configuration
— DECIDED: the existing `validate_profile()` mechanism is sufficient
and must not be bypassed, disabled, or worked around by any future
Activation Plan.** No new validation logic is authorized or required by
this policy pass; the four already-implemented, independently
re-verified checks are affirmed as the governing fail-closed contract
for this activation.

**C4. Whether a dry-run/shadow phase using `bridge_submit=None` should
be mandatory before live activation — DECIDED: yes, mandatory.** A
deployment intending to go live with ADR-037 active must first run at
least one full dry-run period — the complete intended production
configuration (Gate A pairs, Gate B anchors, `enabled_windows`,
`cross_pair_selection_enabled=True`) with `RuntimeOrchestrator`
constructed with `bridge_submit=None` — observing OSE's own log/metric
surface (`opportunity_window_result`, winner selections, `stale`/
`superseded`/`anchor_not_enabled_for_selection` signals) before ever
supplying a real `bridge_submit`. Grounds: this capability already
exists, requires no new architecture (Research §4, re-confirmed by
direct source read of `_run_back_half`'s `bridge_submit is None`
branch), and costs nothing to require. The exact dry-run **duration** is
left to the future Activation Plan (an operational parameter, not a
product-policy value this document must fix).

## D. Safety/adversarial review — re-verified against current source

| # | Scenario | Verified outcome |
|---|---|---|
| 1 | Gate A pair missing from `bridge.allowed_symbols` | Silently excluded from ORB's tracked universe — no startup error (re-confirmed gap; C2 makes manual cross-check a required runbook step until closed in code). |
| 2 | Bridge symbol present but absent from Gate A | No effect — that pair simply never becomes an ORB candidate; legacy strategies for it, if any, are unaffected. |
| 3 | Gate A populated while Gate B empty | `validate_profile()` check 2 fails closed (`cross_pair_selection_enabled=True` requires ≥1 anchor referenced) if the flag is set; if the flag is `False`, fully inert, no error (matches ADR-036 Amendment 1's "narrow/fixed Gate A route" framing). |
| 4 | Gate B populated while `enabled_windows` empty | `validate_profile()` check 3 fails closed when the flag is `True` (non-empty `enabled_windows` required); harmless if the flag is `False`. |
| 5 | `enabled_windows` populated while `cross_pair_selection_enabled=False` | Fully inert by design — `run_cycle()`'s classification logic only enters the barrier path when the flag is `True` (re-verified, `titan_protocol/runtime/engine.py`). |
| 6 | Selection enabled with only one approved ORB pair | `validate_profile()` check 4 fails closed (`len(orb_pairs) <= 1` rejected when the flag is `True`) — re-verified directly. |
| 7 | Configured window without matching anchor | `validate_profile()` check 1 fails closed unconditionally (every `enabled_windows` entry must reference a real, matching `opening_range_anchors` entry) — re-verified directly, runs regardless of the flag. |
| 8 | Anchor without configured window | Only a violation when the flag is `True` (check 2); when `False`, this is exactly ADR-036 Amendment 1's inert/narrow-route configuration, explicitly permitted. |
| 9 | Overlapping anchors | `_validate_no_overlapping_anchors` fails closed at Evidence Engine construction, independent of ADR-037's own checks — re-verified directly. |
| 10 | DST/session-label mismatch | Not automatically detected (§B, above) — governed by the already-Accepted, repository-wide "operator updates the UTC anchor hour/minute twice yearly" convention; a runbook responsibility, not a code gap this policy invents a fix for. |
| 11 | Dry-run vs. live-submit configuration drift | The only difference between the two is the `bridge_submit` constructor argument — every other input (Gate A/B, `enabled_windows`, flag) is identical, so C4's dry-run phase exercises the real intended configuration, not a separate one; the one caveat (Research §4: `CycleOutcome.SUBMITTED` is reported even when `bridge_submit is None`) is a runbook/observability note for whoever writes the dry-run procedure, already flagged, not re-litigated here. |
| 12 | Partial configuration deployment/restart | Restart re-runs `validate_profile()` fresh at every boot (re-verified: no cached/skip-on-restart validation path exists) — a partially-migrated config is refused at the next boot exactly as it would be on first boot; no special partial-restart case exists or is needed. |
| 13 | Multiple enabled windows on the same day | Independently re-verified as already-tested architecture (`TestWindowCardinality`, `tests/titan_protocol/runtime/test_opportunity_selection_barrier.py`) — each window's `range_start` is independently keyed and resolved; no special handling required for three simultaneous windows. |
| 14 | No qualifying candidates | Already-governed, unaltered outcome — empty candidate set produces no winner, no durable store entry, re-evaluable next cycle (Amendment 1 §2). |
| 15 | Tie | Already-decided policy (Decision document §3/§4) — no winner for that window that cycle, `tie_tolerance=0.5` inclusive. |
| 16 | Selector/store failure | Already-governed fail-closed contract (§12's "Absolute requirement," re-verified in the barrier tests) — zero pairs proceed for the affected window that cycle; never falls back to unrestricted execution. |

**No scenario above falls back to unrestricted multi-pair execution** —
independently re-confirmed against the current, conformant
implementation, not assumed from a prior report.

## Decisions made (this document)

- C1: production `enabled_windows`/`cross_pair_selection_enabled`
  values originate from the same deployment JSON config file as Gate
  A/B, via a dedicated OSE-owned config section.
- C2: Gate A, Gate B, `enabled_windows`, and the flag must activate
  together in one verified deployment change; Bridge-symbol/Gate-A
  cross-consistency is a required manual runbook check until a future
  code hardening closes it.
- C3: the existing `validate_profile()` fail-closed contract is
  affirmed as sufficient and must not be weakened.
- C4: a `bridge_submit=None` dry-run phase, using the full intended
  production configuration, is mandatory before live activation.

## Unresolved decisions (explicitly left open — USER DECISION REQUIRED)

- **The exact Gate A production pair list** (§A) — no repository
  evidence uniquely determines it.
- **The exact Gate B anchor UTC hour/minute for London, London–New York
  Overlap, and Early New York** (§B) — no repository evidence uniquely
  determines it; the DST *handling policy* is resolved (operator
  runbook responsibility, per existing convention), but the *initial
  values themselves* are not.

## Recommendations not yet binding

- The `enabled_windows`/`cross_pair_selection_enabled` JSON-loading code
  change (C1's architecture, not yet implemented) and a Gate-A/`bridge.
  allowed_symbols` cross-validation check (D#1's gap) are both
  reasonable future hardening candidates; neither is authorized or
  required to be built by this document.
- A Gate B anchor hour/minute range-validation check (the ADR-035 Phase
  5 residual risk) would improve fail-fast behavior for a mistyped
  anchor; not authorized here, and confirmed non-blocking for a
  correctly-configured deployment.

## Implementation prerequisites (restated from the Research artifact, not resolved here)

- The `enabled_windows`/`cross_pair_selection_enabled` config-loading
  code path does not exist yet and must be built before Gate A/B values
  alone are sufficient to activate ADR-037 from the deployment config
  file (independently re-confirmed: `start.py:1143` still hardcodes
  `OpportunitySelectionEngineConfig()`).

## Explicit authorization boundaries

This document authorizes nothing beyond the four process decisions in
§C. It does not authorize: Gate A or Gate B activation; any exact
production pair, anchor, or clock value; `cross_pair_selection_
enabled=True`; the `enabled_windows` config-loading code change;
legacy-strategy retirement; runner-up fallback; ADR-035 Phase 5 work.
Production activation remains unauthorized regardless of this
document's disposition.

## Validation (this pass)

`compileall` clean (`titan_protocol`, `tests`, `deployment_windows`).
Targeted suites re-run fresh: `opportunity_selection_engine` (68),
`runtime` (189), architecture/structural-boundary suites (5 files, 27
tests) — all green. Gate A closed; Gate B empty;
`cross_pair_selection_enabled=False`; 6 `StrategyId` members; legacy
registry intact (5 strategies, ORB absent); clean tree before, during,
and after this pass; diff confined to this one new documentation
artifact.

---

*This document is a policy-decision artifact. It closes four process
questions (§C) on existing architectural precedent. It does not close,
and does not attempt to close by inventing evidence, the two remaining
irreducible product choices (§A, §B) — those require the user's own
decision. It amends no ADR and authorizes no implementation or
activation.*
