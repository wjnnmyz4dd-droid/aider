# Policy Decision — ADR-037 Ranking, Tie Handling, and Initial Production Sessions

Status: **Policy decision drafted — awaiting independent policy review before
it may inform an ADR-037 implementation Plan.** This document decides
trading-policy and deployment-profile content within the envelope
`docs/plans/adr-037-ranking-tie-session-policy-research.md` (commit
`1d43759`) established as evidenced and unresolved. It amends no ADR,
implements no code, and does not by itself authorize implementation.

Depends on: ADR-037 (Accepted, `527e6ba`); ADR-031 Amendment 1 (Accepted,
`5e6bbea`); the Research artifact above. Every decision below is traceable to
a specific finding in that Research; nothing here reopens the architecture
Research and ADR-037/ADR-031 Amendment 1 already settled.

---

## 1. Repository / governance baseline (re-verified for this pass)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `1d43759`, clean tree,
  in sync with upstream, before this decision pass began.
- ADR-037: Accepted. ADR-031 Amendment 1: Accepted. Research: complete at
  `1d43759`. Re-confirmed by direct read of all three.
- Gate A: `OPENING_RANGE_BREAKOUT` absent from `DEFAULT_APPROVED_PAIRS_BY_
  STRATEGY` — closed, unchanged.
- Gate B: `EvidenceEngineConfig.opening_range_anchors` defaults to `()` —
  empty, unchanged.
- No Opportunity Selection Engine implementation exists anywhere in the
  repository (`grep -rli "opportunity.selection\|OpportunitySelection"
  titan_protocol/` — zero matches).

## 2. Ranking policy — decided

**Decision: for v1, the sole ranking criterion is the highest
`QualificationResult.score`. No secondary ranking criterion is adopted.**

Grounds, each tracing to a specific Research finding:

- `score` is already bounded [0, 100] and pair-scale-independent (Research
  §4) — it already satisfies "identical semantics across pairs" without any
  new normalization work.
- `confidence` is currently a non-discriminating constant (`1.0`) for every
  real ORB `QualificationResult` (Research §4, traced to `evidence_engine/
  scoring.py::score_session()` always setting `confidence=1.0`). Adopting it
  as a secondary criterion, the way `selection.py`'s Step 2 does for
  same-pair comparison, would add a step that never breaks a tie among ORB
  candidates today — a criterion included "to look sophisticated" but
  inert, which this task explicitly instructs against.
- `CLAUDE.md` §6 (Minimal Change Engineer philosophy) and this task's own
  instruction ("do not add weights merely to make the formula look
  sophisticated," "determine the smallest defensible initial ranking
  policy") both favor the smallest rule not yet shown insufficient by any
  adversarial scenario. §9's adversarial pass (below) finds none that
  requires a second criterion.
- This decision is not architecturally binding beyond v1: the Opportunity
  Selection Engine's contract (ADR-037 §6) is "a pure function of [the]
  candidate-set input," deliberately without a fixed formula — nothing here
  forecloses a future, separately-reviewed revision adding a secondary
  criterion if evidence later shows one is needed.

### 2.1 Liquidity/spread disposition — decided

**`liquidity_score` remains an eligibility gate only for v1; it is not
adopted as a secondary ranking criterion.** Research §4 found no
double-counting concern in doing so (liquidity/spread are not in `score`
today), but adding it as a ranking input is itself a policy expansion not
yet justified by any adversarial finding — the smallest defensible policy
is the one-signal rule above, and this is exactly the kind of case §6
governs: three similar lines (i.e., an unforced second criterion) are
tolerated better as a documented "not adopted, could be revisited" decision
than as a criterion added on spec.

**Raw `current_spread` is explicitly not used as a cross-pair tiebreaker.**
Per Research §4/§10, it is a raw pip value with no cross-pair normalization,
and its safety as a ranking input depends on Gate A's eventual width/
composition (unresolved, out of scope here per this task's §7). No
normalization is justified in this pass, so it is not adopted, consistent
with this task's explicit instruction.

**`TradeReadiness`, Research Engine pair rankings, and any Risk/Compliance
output are not used.** Per Research §3/§11, the first two are documented
advisory-only under their own owning ADRs' Hard Rules (ADR-025 Hard Rule 6,
ADR-029 Hard Rule 2) and the last two are architecturally unavailable
pre-Risk. Using any of them would require governance this task does not
grant.

## 3. Tie policy — decided

**Decision: Option A — a tie within the established tolerance produces no
winner for that opportunity window.**

Reasoning: Research §5 found two contradictory existing precedents. Given
§2's decision that v1 has no secondary ranking criterion, Option B
("deterministic secondary ranking criterion") is unavailable without
inventing a new, unforced criterion — the same objection §2.1 already
raised. Option C (alphabetical/symbol-order winner) is explicitly the
pattern this task instructs to be wary of ("prefer a rule that does not
manufacture economic significance from symbol ordering") — `evidence_engine/
ranking.py`'s symbol-ascending tiebreak is a defensible convention for an
*advisory display ordering* that commits no capital, but using it to decide
which pair's trade actually executes would let an arbitrary alphabetical
label determine a real capital-committing outcome between two candidates
the system itself judged equally good. Option D (random) is excluded per
explicit instruction and was never a candidate this codebase's own
precedent supports. Option A matches `selection.py`'s own already-Accepted-
architecture precedent (already cited, non-bindingly, by ADR-037 §6) and
`CLAUDE.md` §2's "capital preservation overrides profit" — a genuinely
indistinguishable-quality opportunity produces no trade that cycle for that
window, rather than an arbitrary pick standing in for a decision the system
could not actually make.

## 4. Tie tolerance — decided

**Decision: reuse the established `0.5` score-point tolerance, applied with
the same `<=` (inclusive) boundary `selection.py::_narrow_by()` already
uses: two candidates are tied when `best_score - candidate_score <= 0.5`.**

This boundary is not guessed — it is read directly from existing,
already-Accepted source: `_narrow_by()` (`strategy_engine/selection.py:34-38`)
computes `best = max(...)` and keeps every candidate satisfying `best -
key(c) <= tolerance`, i.e., a difference of exactly `0.5` already counts as
tied under the established pattern. Reusing this exact boundary, rather than
inventing a strict `<` variant, is the only choice consistent with "do not
invent a new epsilon without evidence" — the evidence specifies `<=`
precisely.

**What is decided vs. left to the Plan:** the *value* (`0.5`) and the
*boundary semantics* (`<=`, inclusive) are decided here, as policy, because
both are directly evidenced. **Left to the Plan:** whether the Opportunity
Selection Engine's tolerance is literally the same `StrategyEngineConfig.
score_tie_tolerance` field reused across engines, or a new, independently-
named config field on the Opportunity Selection Engine's own config that
defaults to the same value — Research §6 already flagged that literally
sharing a field across two unrelated engines is itself a new cross-engine
coupling requiring its own justification, which is implementation wiring,
not policy content, and is correctly Plan-level work.

## 5. Initial production-session decision

**Decision: the initial production-policy content is two enabled
opportunity windows — London and Early New York — with `LONDON` and
`EARLY_NEW_YORK` as the two `SessionName` values.**

**Evidence for the "New York" interpretation (§8 of this task), found, not
guessed:** `MarketIntelligenceConfig.preferred_sessions` (`market_
intelligence/config.py:40-43`) already defaults to exactly `(SessionName.
LONDON, SessionName.LONDON_NEW_YORK_OVERLAP, SessionName.EARLY_NEW_YORK)` —
an existing, already-Accepted (ADR-025), already-shipped preference default
that already excludes `LATE_NEW_YORK` and `ASIAN`. This is corroborated by
`evidence_engine/session.py`'s own `SESSION_QUALITY_SCORES` table (ADR-024,
Accepted): `LONDON_NEW_YORK_OVERLAP=100`, `LONDON=80`, `EARLY_NEW_YORK=75`,
`LATE_NEW_YORK=55` (notably lower — the lowest-scoring tradeable session
after Asian), `ASIAN=40`, `CLOSED=10`. Both tables — independently produced,
under different Accepted ADRs, for different purposes (MI preference
weighting vs. Evidence session-quality scoring) — agree that `EARLY_NEW_YORK`
is the New-York-family session this system already treats as valuable, and
that `LATE_NEW_YORK` is not.

**Why not `LONDON_NEW_YORK_OVERLAP` as the second window:** the product
intent named in this task is explicitly **"the two principal sessions:
London and New York"** — two, not three. `LONDON_NEW_YORK_OVERLAP` is its
own distinct `SessionName`, not a sub-interval of "New York" or "London" in
the enum's own vocabulary, and treating it as either would make the initial
policy a de facto three-window (or ambiguous two-window-with-overlap-
folded-in) policy that this task's own framing does not ask for. Nothing in
this decision forecloses adding `LONDON_NEW_YORK_OVERLAP` as a third,
independently-configured window in a later, separately-reviewed policy
revision — the configurable-list architecture (§6 below) already supports
that without any code change.

**Why not `LATE_NEW_YORK`:** it is excluded from the existing `preferred_
sessions` default and scores lowest of the four tradeable, non-Asian
sessions (55, versus Early New York's 75) in the already-Accepted quality
table. No repository evidence supports it as the intended "New York" content;
it is not adopted.

**What remains explicitly not decided here, per this task's own
instruction:** the exact anchor clock hour/minute for either window's
opening range. `SessionName` labels a *kind* of session (per ADR-037 §8,
descriptive only, never the identifying key); the actual Gate B anchor
(`opening_range_anchors` entry) that realizes "the opening range for London"
or "the opening range for Early New York" as a concrete `(SessionName, hour,
minute)` tuple is deployment-profile content this task explicitly reserves,
and this document does not choose it. (`evidence_engine/config.py`'s own
`london_session_start_hour`/`early_new_york_end_hour`-style fields describe
*session classification* boundaries for Evidence/MI scoring — a separate
mechanism from Gate B's `opening_range_anchors`, per ADR-037 §8/§11's
explicit "third, independent configuration concept" language — and are not
themselves opening-range anchor values, so they do not by themselves settle
an anchor choice either.)

## 6. Session configurability contract (restated, not altered)

Unchanged from ADR-037 §8/§11 and ADR-031 Amendment 1 §11, restated here as
the frame this policy operates inside:

- Enabled windows are configuration-driven, never a code constant.
- Zero, one, two, or more windows remain architecturally representable at
  all times.
- **This decision's choice of two (London, Early New York) is production
  policy content, not an architectural bound** — nothing in the
  Opportunity Selection Engine or Runtime may hardcode "exactly two" or
  name either session directly; both must be ordinary configured entries.
- Enabling or disabling a window is a configuration change only, never a
  selection-architecture change.

## 7. Gate A interaction

**No exact production Gate A pair list is chosen or required by this
decision.** The ranking policy (§2) operates identically regardless of Gate
A's eventual width, because `score` is pair-scale-independent (Research §4)
— the ranking rule imposes no new constraint on, and requires no change to,
Gate A's composition. Gate A remains, per ADR-037 §11 (unaltered), the
*candidate universe a session scans*, never the ranking mechanism itself —
this decision does not blur that distinction. The exact production pair
list remains unresolved, explicitly deferred to the ADR-036/ADR-037
implementation Plan, exactly as Research §10 and ADR-037 §17 already state.

## 8. Gate B interaction

**No anchor hour/minute values are chosen.** The only relationship this
decision requires, restating ADR-037 §7–§9/§11 without alteration: each of
the two initial production windows (London, Early New York) must resolve,
when eventually configured, to its own valid, non-overlapping Gate B anchor
entry; each window's `range_start` and selection are computed and resolved
independently (Research §9, re-confirmed, not reopened); no winner from one
window ever carries into the other. Exact anchor clock times remain future
deployment-profile content, not decided here.

## 9. Adversarial pass — proposed policy against required scenarios

| # | Scenario | Result under this policy |
|---|---|---|
| 1 | One qualifying pair | Sole candidate wins — no tie question arises |
| 2 | Multiple pairs, clearly different scores | Highest `score` wins (§2) — no ambiguity |
| 3 | Exact score tie | Difference is `0` `<= 0.5` → tied → no winner for that window (§3/§4) |
| 4 | Scores inside tolerance (e.g. 0.3 apart) | `<= 0.5` → tied → no winner (§4) |
| 5 | Scores just outside tolerance (e.g. 0.51 apart) | `> 0.5` → not tied → higher-score candidate wins outright |
| 6 | Pair iteration order reversed | No effect — ranking is a pure function of `score` values, not input order (ADR-031 Amendment 1 §8's deterministic-assembly-order requirement, unaltered, guarantees this independently of which ranking rule is chosen) |
| 7 | Higher score, worse-but-still-eligible liquidity | Higher-score candidate still wins — liquidity is a gate the candidate already passed, not a ranking input in v1 (§2.1) |
| 8 | Higher score, wider-but-still-eligible spread | Same as #7 — spread is a gate, not a ranking input in v1 |
| 9 | London winner, then independent New York scan | Each window's scan/selection is fully independent (§8, Research §9) — London's winner has no effect on New York's candidate set or outcome |
| 10 | Same pair wins both windows independently | Explicitly permitted, unchanged from ADR-037 §9 — `range_start`-alone identity means each window is its own key |
| 11 | London tie, New York clear winner | London: no winner (§3). New York: highest-score candidate wins. The two outcomes are computed and recorded independently; neither affects the other |
| 12 | One enabled window | Policy applies identically — cardinality is a configuration matter (§6), not a policy-rule dependency |
| 13 | Two enabled windows | The initial production case (§5) — no special-casing required |
| 14 | More than two enabled windows | Policy applies identically to each window's own independent candidate set — no architectural or policy change needed for a third or later window |
| 15 | Disabled window | Produces no candidates for that window by construction (ADR-037 §5.C/§11) — this policy is never invoked for it |
| 16 | Selector failure | Governed by ADR-037 §7/§12's existing fail-closed rule (zero winners, no fallback) — unaffected by, and not weakened by, this ranking/tie policy |
| 17 | Missing ranking input (`score` itself unavailable for a candidate) | Cannot occur for a candidate that reached `QUALIFIED` status — `score` is populated as part of qualification itself (Research §3/§4); a pair that never produced a terminal front-half outcome is excluded before reaching the selector at all by ADR-037 §5.D/§7's completeness rule, unaltered here |

**No scenario above falls back to unrestricted multi-pair execution.**
Every "no winner" outcome (ties, disabled windows, selector failure) is
scoped to that window/cycle only, consistent with ADR-037 §5/§7/§12's
already-Accepted fail-closed contract, which this policy decision does not
alter or weaken.

## 10. Configuration-ownership determination

**Recommendation for the Plan (not implemented here): the enabled-
opportunity-window list and the Opportunity Selection Engine's own
tie-tolerance parameter should be owned by a new, dedicated config
dataclass belonging to the Opportunity Selection Engine itself** — the same
per-engine-owns-its-own-config pattern every existing pipeline-stage engine
already follows (`EvidenceEngineConfig`, `MarketIntelligenceConfig`,
`StrategyEngineConfig`, `RiskEngineConfig`, `ComplianceEngineConfig`, each
owned by its own package, referenced together by `TradingProfile`/
`validate_profile()` for cross-component fail-closed checks). This is the
smallest architecturally appropriate home because:

- The Opportunity Selection Engine is already established (ADR-037 §4) as
  its own, independent, pipeline-stage-level component — giving it its own
  config is the existing pattern applied, not a new architectural decision.
- `EvidenceEngineConfig` already owns Gate B (`opening_range_anchors`); the
  enabled-sessions list is explicitly a **third, independent** concept
  (ADR-037 §11) that only *references* Gate B anchors by identity — it does
  not belong inside `EvidenceEngineConfig` any more than inside
  `StrategyEngineConfig`.
- `ADR-031 Amendment 1 §1` already cites `validate_profile()`'s existing,
  open-ended extensibility (established by ADR-036 Amendment 1) as the
  correct home for the cross-component fail-closed checks ADR-037 §11
  requires — a new engine-owned config, referenced from `validate_profile()`
  the same way every other engine's config already is, fits this precedent
  exactly, without inventing a new validation mechanism.

**This is a recommendation for the future Plan, not an implementation** —
no config class, field, or file is created by this document.

## 11. Governance artifact and next gate

Per this task's §11: no architectural contradiction was found anywhere in
this decision pass, so no new ADR is created and ADR-037/ADR-031 Amendment 1
are not amended. This document is the dedicated policy-decision artifact
recording the outcome, created (per this task's own instruction) **before**
any implementation Plan drafting, so that the policy content itself can
receive its own independent review — consistent with this repository's
established RPI/governance-gate discipline (every substantive artifact this
session has received an independent review before being relied upon by the
next step).

## 12. Explicit non-authorization (restated)

This document does not authorize, and no future work may cite it as having
authorized: Opportunity Selection Engine implementation; any Runtime
implementation change; Gate A or Gate B activation; the exact production
Gate A pair list; exact opening-range anchor clock times; legacy-strategy
retirement; any runner-up fallback policy; the ADR-035 Phase 5 anchor
hour/minute validation follow-up (separately gated, unauthorized, unrelated
throughout).

## 13. Unresolved policy decisions (explicitly left open)

- Whether a secondary ranking criterion should ever be added (not adopted
  for v1; revisitable only via a future, separately-reviewed decision).
- The exact production Gate A pair list.
- The exact opening-range anchor clock hour/minute for the London and Early
  New York windows.
- Whether `LONDON_NEW_YORK_OVERLAP` should become a third production
  window in a later revision.
- The Opportunity Selection Engine's own config class name/module
  placement (recommendation given in §10; not implemented).
- Whether the tie-tolerance value should literally share `StrategyEngine
  Config.score_tie_tolerance` or be an independently-named field with the
  same default (Plan-level wiring decision, §4).
- The stale pre-Acceptance "Proposed" wording still present in ADR-031
  Amendment 1's own §12/footer (carried forward from the Research artifact,
  §1 there) — a documentation-only defect, not corrected in this pass.

---

*This document is a policy-decision artifact. It requires its own
independent policy review before it may inform an ADR-037 implementation
Plan. It authorizes no implementation.*
