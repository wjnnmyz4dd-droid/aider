# Research — ADR-037 Ranking, Tie, and Production-Session Policy

Status: **Research artifact — read-only findings, no governance decision made here.**

Scope: this document researches the three product-policy questions ADR-037
(Accepted, `527e6ba`) and ADR-031 Amendment 1 (Accepted, `5e6bbea`) both
explicitly left unresolved — ranking rule, tie-handling rule, and production
session/pair/anchor content — and their interaction with the already-Accepted
architecture. It makes **no** decision, drafts no ADR/amendment text, and
authorizes no implementation. Per this task's explicit instruction, it treats
the ADR-037/ADR-031-Amendment-1 architecture as settled and out of scope for
reopening; every finding below is either (a) an inventory of existing,
already-computed signals, (b) an analysis of whether/how those signals could
satisfy the unresolved policy questions, or (c) a disclosed
dependency/ambiguity that a future policy decision must address — never a
proposed formula, weight, tie rule, or session list.

---

## 1. Repository / governance baseline (independently re-verified)

- Branch `claude/phantom-ea-visibility-cjjf3a`, HEAD `5e6bbea`, working tree
  clean, in sync with `origin/claude/phantom-ea-visibility-cjjf3a` before this
  research began (`git rev-parse HEAD` == `git rev-parse @{u}`).
- `docs/adr/ADR-037-orb-cross-pair-session-opportunity-selection.md`: Status
  line reads `**Accepted** (2026-07-28 — governance/architecture decision
  only...)`. Confirmed by direct read of the full file (§1–§17).
- `docs/adr/ADR-031-runtime-orchestrator.md` Amendment 1: header reads
  `# Amendment 1 (2026-07-29, Accepted 2026-07-29 — history preserved below,
  not backdated) — ...` with a `**Status: Accepted.**` paragraph. Confirmed by
  direct read of lines 339–801.
- **Documentation inconsistency found, not fixed (out of scope for this
  Research task — modifying an Accepted ADR is explicitly prohibited by this
  task's own instructions):** the Amendment 1 acceptance edit (commit
  `5e6bbea`) updated the header block but did not update two leftover
  Proposed-era sentences later in the same section: §12's own last acceptance-
  criteria bullet still reads *"This amendment remains **Proposed** and
  self-evidently does not mark itself Accepted"* (line 791), and the closing
  italic footer still reads *"This amendment is Proposed. It requires its own
  independent governance review before Acceptance"* (lines 796–801). Both now
  contradict the header's `Accepted` status and the "Governance review and
  acceptance history" paragraph immediately above them. This is a pure
  documentation staleness defect (no substantive/architectural content is
  affected — nothing in §1–§12's operative contract is contradicted), but it
  should be corrected in a future administrative pass analogous to the one
  that already accepted this amendment. **Not corrected here** — this task is
  Research only, ADR modification is explicitly out of scope, and this is
  exactly the kind of self-authored architectural change this task's
  instructions forbid.
- Gate A: `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` contains no
  `OPENING_RANGE_BREAKOUT` entry (only the five legacy strategies) —
  confirmed by direct execution: `OPENING_RANGE_BREAKOUT in
  DEFAULT_APPROVED_PAIRS_BY_STRATEGY` → `False`. **Closed, unchanged.**
- Gate B: `EvidenceEngineConfig.opening_range_anchors` defaults to `()` —
  confirmed by direct source read (`evidence_engine/config.py:78`).
  **Empty, unchanged.**
- No Opportunity Selection Engine implementation exists anywhere in the
  repository — confirmed by `grep -rli "opportunity.selection\|
  OpportunitySelection" titan_protocol/` returning zero matches.
- No ADR-036 legacy-strategy retirement work exists — `StrategyId` still has
  exactly 6 members (5 legacy + `OPENING_RANGE_BREAKOUT`), confirmed by direct
  execution.

No intervening change to any of the above was found. The governance baseline
stated in this task's prompt is independently confirmed, not assumed.

## 2. Architecture vs. policy — what remains untouched

Per this task's §2, the following ADR-037/ADR-031-Amendment-1 decisions are
treated as settled and are **not** re-examined, re-argued, or reopened by
anything below: dedicated Opportunity Selection Engine ownership; pre-Risk
placement; one-winner-per-`range_start` cardinality; fail-closed incomplete-
scan behavior; `range_start`-alone identity; persisted winner state design;
arbitrary session-list cardinality. Every finding below is scoped strictly to
the four open policy questions (A–D in this task's own framing): "best
opportunity" meaning, tie behavior, initial enabled-session content, and
enabled-session-list configuration ownership.

## 3. Ranking-signal inventory

Every score/quality field available to a pre-Risk ranking decision, traced to
its exact source and classified:

| Signal | Source | Range | Classification |
|---|---|---|---|
| `QualificationResult.score` | `orb_breakout.py::qualify()` (strategy_engine/strategies/orb_breakout.py:213) | 0–100 (clamped) | Already part of strategy qualification |
| `QualificationResult.confidence` | same, = `session_component.confidence` | constant `1.0` for every real evaluation (see §4) | Already part of strategy qualification, but see §4 — non-discriminating |
| `QualificationResult.strengths`/`weaknesses` | same | free text | Already part of strategy qualification — human-readable, not a ranking number |
| `StrategySnapshot.trade_intent` | strategy_engine/models.py | `BUY`/`SELL`/`NONE` | Already part of strategy qualification — directional, not a ranking magnitude |
| Evidence session-component value | `evidence_engine/scoring.py::score_session()` | 0–100 | Already embedded in ORB's own `score` (0.4 weight, as `session_value`) |
| Evidence volatility score | `evidence_engine/scoring.py::score_volatility()` | 0–100 | Already embedded in ORB's own `score` (0.3 weight) |
| MI session score (`SessionIntelligence.session_score`) | `market_intelligence/session_intelligence.py` | 0–100 | Already embedded in ORB's own `score` (0.3 weight, as `mi_session_score`) |
| FVG confirmation bonus | `orb_breakout.py` (binary, ×`config.orb_fvg_score_weight`, default 0.15) | 0 or 100×weight | Already embedded in ORB's own `score` |
| `LiquidityIntelligence.current_spread` | `market_intelligence/liquidity_intelligence.py` | raw pips, unbounded, pair-scale-dependent | Pair-level market-quality information — **already a hard gate** (`orb_max_spread_pips`), never in `score` |
| `LiquidityIntelligence.liquidity_score` | same | 0–100, **self-normalized** (ratio of current/average spread for that pair, not an absolute pip value) | Pair-level market-quality information — **already a hard gate** (`orb_min_liquidity_score`), never in `score` |
| `PairNewsIntelligence.news_score` | `market_intelligence/news.py` | 0–100 | Pair-level market-quality information — not consumed by ORB's `score` or by any existing gate in `orb_breakout.py` |
| `MarketSafetyStatus.safety_score` | `market_intelligence/market_safety.py` | 0–100 | Pair-level market-quality information — underlying booleans (`market_closed`, `is_holiday`) are hard gates in `orb_breakout.py`; the composite score itself is not consumed there |
| `PairSafety.pair_safety_score` | `market_intelligence/scoring.py::build_pair_safety()` | 0–100, composite of news/liquidity/session/market-safety | Pair-level market-quality information — **already re-embeds `session_score`**, which ORB's own `score` also already embeds directly (see §4's double-count warning) |
| `TradeReadiness.readiness_score` | `market_intelligence/scoring.py::build_trade_readiness()` | 0–100, composite of `pair_safety_score` + session/liquidity/news again | **Unsuitable for pre-Risk ranking without a governance decision** — ADR-025 Hard Rule 6 documents it as "advisory only — never consulted by anything with authority to place, size, or approve a trade" (`market_intelligence/models.py:173-176`); also re-embeds session/liquidity/news a second and third time (see §4) |
| Research Engine `pair_intelligence.rank_pairs()` (win rate, profit factor, Sharpe, Sortino, expectancy, avg R, drawdown per pair) | `research_engine/pair_intelligence.py` | ranked, not a single scalar | **Unsuitable for pre-Risk ranking without a governance decision** — ADR-029 Hard Rule 2 documents Research Engine as "Completely advisory: never places, rejects, sizes, or [decides]" (`research_engine/engine.py:2`); this is exactly the "historical strategy ranking" input `selection.py`'s own Step 3 comment names as not yet available — it is now available, but consuming it here would be new, unauthorized cross-engine coupling and a new consumer of an explicitly advisory-only signal |
| `RiskSnapshot.exposure_summary`, `.correlation_status`, `.recommended_position_size` | `risk_engine/models.py:203-214` | n/a | **Risk-owned information — unavailable pre-Risk by construction** (Risk Engine has not run yet at the point selection occurs); see §11 |
| Compliance decision/score | `compliance_engine` | n/a | **Compliance-owned information — unavailable pre-Risk by construction** |

**No double-counting exists in the current `QualificationResult.score`
formula itself** — session/volatility/MI-session/FVG are each counted exactly
once, with weights summing to 1.0 plus a separately-weighted FVG bonus,
clamped to [0, 100]. The double-counting risk identified above is
prospective: it would arise **only if** a future ranking policy adds
`pair_safety_score` or `readiness_score` as an *additional* ranking factor
alongside ORB's own `score`, since both already re-embed `session_score`
(and, for `readiness_score`, `liquidity_score`/`news_score` as well, on top
of `pair_safety_score`'s own inclusion of the same). This is disclosed as a
risk for whichever policy decision is made later; no signal is chosen or
rejected here.

## 4. ORB-score sufficiency assessment

**`QualificationResult.score` is already a bounded, cross-pair-comparable
quantity** — every input to it (`session_value`, `mi_session_score`,
`volatility_score`, `fvg_bonus`) is independently clamped/scored to a [0, 100]
range by its own producing component, with no pair-specific scale, currency,
or pip-value dependency anywhere in the formula
(`0.4*session_value + 0.3*mi_session_score + 0.3*volatility_score +
config.orb_fvg_score_weight*fvg_bonus`, then `clamp()`ed). This directly
challenges (favorably) the "does score have identical semantics for all
pairs" question: yes, by construction, because none of its components are
pair-scale-dependent — a JPY pair's differing pip value, for instance, never
enters this formula (it is instead confined to `current_spread`'s raw-pip
representation, which never enters `score`).

**`confidence` is not independent information for ORB specifically.**
Verified from source: `orb_breakout.py`'s `confidence = session_component.
confidence if session_component else 0.5`, and `evidence_engine/scoring.py::
score_session()` **always** sets `confidence=1.0` unconditionally — it does
not vary with session quality, pair, or any other input. `compute_component_
scores()` (`evidence_engine/scoring.py:141-158`) always includes a session
component in `EvidenceReport.score.components`, so the `else 0.5` branch is
unreachable in practice for any real evaluation (structurally analogous to
`orb_breakout.py`'s own documented "unreachable... retained as defense-in-
depth" pattern elsewhere in the same file). **Consequence: every real
`QualificationResult` produced by `OrbBreakoutStrategy` carries `confidence
== 1.0`.** A ranking rule that incorporates `confidence` as a second axis
(the way `selection.py`'s Step 2 does for same-pair cross-strategy
comparison) would, for ORB-only cross-pair comparison specifically, add no
discriminating information today — every ORB candidate ties on this field by
construction. This is a genuine finding, not an assumption: it means
`selection.py`'s two-step (`score`, then `confidence`) precedent does not
transfer to ORB-only cross-pair ranking without modification, since step 2
would never break a tie among ORB candidates as currently computed.

**Liquidity/spread are gating, not scoring, inputs today**, confirmed direct
from `orb_breakout.py:108-115`: `current_spread > config.orb_max_spread_pips`
and `liquidity_score < config.orb_min_liquidity_score` are both early-return
`NOT_QUALIFIED` checks, never blended into `score`. This means: (a) using
`liquidity_score` as an *additional* ranking input alongside `score` would
not double-count anything already in `score` (it genuinely is not there
today) — it would add new information, not duplicate existing information;
(b) `current_spread` itself is a raw pip value, not self-normalized, and pip
value differs by pair (JPY-quote pairs use a different pip scale than most
others in `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`, e.g. `USDJPY`, `EURJPY`,
`GBPJPY` are already present in the strategy-engine-wide approved-pairs
config today, confirmed by direct read of `strategy_engine/config.py`'s
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`) — so `current_spread` is **not**
directly cross-pair comparable without a normalization step, whereas
`liquidity_score` (built from the *ratio* of current to that pair's own
average spread, not an absolute value) already **is** self-normalizing and
cross-pair comparable by construction (`liquidity_intelligence.py:17-34`).

**No formula is adopted here.** This section establishes only that `score`
alone already satisfies "identical semantics across pairs" and "bounded,
comparable range," and that `confidence` does not currently add
discriminating power for ORB-only comparison — evidence for, not a decision
of, whatever ranking rule a future Plan states and justifies.

## 5. Tie-policy options (existing repository precedent, not a decision)

Two genuinely distinct existing repository precedents were found for
cross-item comparison with ties, pointing toward different defaults:

1. **`selection.py::select_winning_strategy()`** (same-pair, cross-strategy,
   the closest structural analog): a six-step deterministic cascade
   (score → confidence → [historical ranking, no-op placeholder] →
   [portfolio concentration, no-op placeholder] → liquidity → news), each
   step narrowing to candidates within `config.score_tie_tolerance` of the
   best value; **"still tied after all six steps: reject, never randomize"**
   (`selection.py:81-82`). ADR-037 §6 already cites this exact precedent as
   "a strong candidate default... given this codebase's established risk
   posture," without adopting it.
2. **`evidence_engine/ranking.py::rank_pairs()`** (cross-pair, but advisory-
   only ordering, not a decision — "Ranks already-scored pairs highest-first.
   Never selects a trade — it only orders reports that already exist"):
   `sorted(reports, key=lambda r: (-r.score.composite, r.symbol))` — ties
   broken by **symbol name ascending**, always producing a single winner,
   never "no result." This is a second, independent, already-established
   deterministic-ordering convention in the same codebase, but it resolves
   ties with a **secondary deterministic key** rather than rejecting —
   the opposite default from (1).

**These two precedents do not point to the same answer**, and this is a
genuine, disclosed finding: whichever tie policy a future Plan adopts for the
Opportunity Selection Engine must explicitly choose between (or justify a
departure from) these two existing, contradictory conventions — "reject on
tie" (the same-pair cross-strategy precedent, capital-preservation-postured,
already cited by ADR-037 §6) versus "deterministic secondary key, always
produce an answer" (the cross-pair display-ranking precedent). Per this
task's own instruction, **no adoption is made here**; ADR-037 §6's own
language ("does not adopt it as binding") is not overridden or narrowed by
this research. Capital-preservation posture (`CLAUDE.md` §2) argues for
weighting precedent (1) more heavily if a single answer is eventually needed,
but this document does not decide that.

Random selection was not found anywhere in the repository as a resolution
strategy for any comparable cascade and is not suggested as a candidate here.

## 6. Tie-precision findings

**`selection.py`'s existing `config.score_tie_tolerance` (default `0.5`,
`strategy_engine/config.py:79`) is the established repository precedent for
"what constitutes a tie."** It is explicitly a **tolerance-band** definition,
not exact floating-point equality: `_narrow_by()` (`selection.py:34-38`)
computes `best = max(key(c) for c in candidates)` and keeps every candidate
with `best - key(c) <= tolerance`. Confidence comparison in the same cascade
uses a **rescaled** tolerance (`config.score_tie_tolerance / 100.0`) to
account for confidence's 0–1 range versus score's 0–100 range
(`selection.py:59`) — i.e., the existing precedent already handles differing
signal scales by dividing the tolerance, not by inventing a separate,
unrelated epsilon per field.

This existing precedent directly answers the "exact vs. normalized vs.
tolerance/epsilon" question with evidence: the repository already has one
established answer (tolerance-band, scale-adjusted per field) for the
structurally closest existing comparison (same-pair cross-strategy). Exact
floating-point equality is not used anywhere in this codebase for a
score-based tie decision found during this research. **This document does
not decide that the Opportunity Selection Engine must reuse `score_tie_
tolerance` itself (a shared config field across an unrelated engine would
itself be a new cross-engine coupling requiring its own justification) — only
that reusing its *pattern* (a named, configured tolerance, not an arbitrary
inline epsilon, and not bare floating-point equality) is the evidenced
precedent this codebase already follows twice (Strategy Engine cascade and,
implicitly, nowhere in `evidence_engine/ranking.py`, which never treats
composite scores as "tied" at all — it always resolves via the symbol
secondary key regardless of score closeness).** This asymmetry itself is a
finding: the codebase's only two ranking mechanisms differ on whether
"almost equal" is even a distinct concept from "not equal," not just on what
happens once a tie is detected.

## 7. Production-session-policy findings

**`SessionName` (`evidence_engine/models.py:214-220`) has six members: `ASIAN`,
`LONDON`, `LONDON_NEW_YORK_OVERLAP`, `EARLY_NEW_YORK`, `LATE_NEW_YORK`,
`CLOSED`.** There is **no** plain `NEW_YORK` member. This is a direct,
material finding against this task's own stated intended direction ("London
enabled; New York enabled"): **"New York" does not map to a single existing
`SessionName` value** — a future production-policy decision enabling "New
York" must specify explicitly whether it means `EARLY_NEW_YORK`,
`LATE_NEW_YORK`, `LONDON_NEW_YORK_OVERLAP`, some combination, or a
newly-configured anchor whose `SessionName` label is chosen independently of
which of these four values best describes its clock window. This ambiguity
is a **policy** question (which of the existing vocabulary values, or
combination, constitutes the intended "New York" session), not an
architecture gap — ADR-037 §8's decision that `SessionName` is descriptive-
only and `range_start` alone is the identifying key means this ambiguity
cannot corrupt any persisted state or selection outcome; it only means the
eventual policy decision cannot simply say "enable New York" without also
resolving which `SessionName`(s)/anchor(s) that maps to. **Not resolved
here.**

**"Enabling by anchor/window rather than `SessionName`" is exactly what
ADR-031 Amendment 1 §11 already requires**, confirmed by direct re-read:
"an enabled-session entry... references one specific configured
`opening_range_anchors` entry (not merely a `SessionName` label)... carries
`SessionName` only as a descriptive/observability field" (ADR-037 §8,
restated without change by ADR-031 Amendment 1 §2/§11). This is fully
consistent with, not contradicted by, the finding above — it is precisely
why the architecture is *not* blocked by the `SessionName` ambiguity, even
though the eventual policy content is.

No existing configuration or ADR text distinguishes an intended production
"New York window" clock time — this remains, per ADR-037 §2/§8/§11 and
ADR-031 Amendment 1 §11, explicit unauthorized product-policy content, not
decided or assumed here.

## 8. Configurable-session-list implications

Confirmed, by direct re-read of ADR-037 §8/§11 and ADR-031 Amendment 1 §11,
that the enabled-sessions list is already architecturally required to be:

- a **list of independent entries**, each referencing one specific Gate B
  anchor, with an enable/disable flag — cardinality is a **list-length
  matter**, never a code change (ADR-037 §8's "An 'enabled session'
  configuration entry, revised").
- coupled to a **fail-closed structural-readiness invariant** (ADR-037 §11,
  unaltered by ADR-031 Amendment 1) requiring: every enabled entry references
  an existing Gate B anchor; every Gate B anchor not represented in the
  enabled list is a startup misconfiguration under the broad-Gate-A flavor;
  an empty enabled list combined with broad Gate A is unsafe and must be
  detected.

This research adds no new implication beyond what §8/§11 already establish —
it confirms the existing text already fully supports zero, one, two, or
arbitrarily many enabled windows without any architectural change, and that
"London + New York" is correctly described everywhere already read as
*intended initial content*, never an upper bound or hard-coded pair. No
config-ownership component (which module loads/validates this list) is named
by ADR-037 or ADR-031 Amendment 1 beyond "extends `validate_profile()`'s
already-established pattern" (ADR-031 Amendment 1 §1, citing ADR-036
Amendment 1 precedent) — the exact ownership module is Plan-level work, not
decided here.

## 9. Cross-session independence

Re-confirmed directly against ADR-037 §8/§9 (unchanged, not reopened):
`range_start` alone is the persisted-winner key; `_validate_no_overlapping_
anchors` (`evidence_engine/config.py:129-148`) already guarantees no two
configured anchors' `[range_start, range_end)` windows can coincide or
overlap; `range_start` is a full `datetime` including the calendar date
(`opening_range.py:137`), so a new day is automatically a new key and a
restart recomputes the identical key for the same real-world window. This
means: a fresh scan/selection per opportunity window, no automatic winner
carryover between windows, and the same pair legitimately winning multiple
distinct windows independently are all **already guaranteed by the Accepted
architecture**, with no policy content required to achieve them. **No
ambiguity found here** — this section exists only to confirm the property
this task asked to verify, not to add new analysis.

## 10. Candidate-universe implications

Re-confirmed from `strategy_engine/config.py`'s `DEFAULT_APPROVED_PAIRS_BY_
STRATEGY`: the current (legacy-strategy) approved-pairs universe already
spans pairs with materially different pip scales and typical spread
magnitudes (e.g. `EURUSD`, `USDJPY`, `EURJPY`, `GBPJPY`, `AUDNZD`). Per §4's
finding, `QualificationResult.score` itself has no pair-scale dependency, so
a ranking rule built solely on `score` is **not** distorted by a broad,
heterogeneous Gate A universe. A ranking rule that also incorporated raw
`current_spread` (pips) **would** need an explicit normalization step before
cross-pair comparison, since pip value differs by quote currency — whereas
`liquidity_score` (self-normalized to each pair's own average) would not.
**This is exactly the dependency this task's §10 asked to identify
explicitly: whichever future ranking-policy Plan decides to include
`current_spread` (rather than `liquidity_score`) as a ranking input cannot
finalize that decision independently of Gate A's eventual production width
and composition** — a narrow, currency-homogeneous Gate A might tolerate raw
spread comparison; a broad, heterogeneous one would not. This document does
not resolve which signal (if any) a future policy chooses, nor Gate A's
production content — both remain open, and this dependency is disclosed, not
decided, exactly as this task's instructions require. No pair category was
found in the current config requiring exclusion rather than ranking
adjustment; nothing in the repository suggests otherwise, but Gate A's
eventual width is itself unresolved, so this cannot be fully closed out
without that separate decision.

## 11. Risk boundary

Every currently-inventoried candidate ranking signal (§3) lives in Evidence
Engine, Market Intelligence, or Strategy Engine output — **none** requires a
Risk Engine output. Confirmed directly: `RiskSnapshot.exposure_summary`,
`.correlation_status`, and `.recommended_position_size`
(`risk_engine/models.py:203-214`) are all fields Risk Engine itself populates
during its own `evaluate()`/`evaluate_batch()` call, which — under ADR-037's
Accepted pre-Risk placement — has not yet run for any candidate at the point
selection occurs. **No architectural contradiction is found**: "best
qualifying opportunity" can be fully determined using only
Evidence/MI/Strategy-Engine-produced signals, without requiring expected
position size, correlation exposure, portfolio concentration, or account
margin — all of which remain correctly Risk-owned and downstream, unaffected
and unconsulted by this research, consistent with ADR-037 §6/§10's already-
Accepted contract that this document does not reopen.

## 12. Runner-up-policy dependency

**Ranking-policy determination does not require resolving runner-up
fallback policy first.** The ranking function's job (as ADR-037 §6 already
specifies, unaltered) is to select a winner from a *complete* candidate set —
a pure function producing `Optional[pair]`. Whether a downstream Risk/
Compliance rejection of that winner triggers any fallback (ADR-037 §10,
explicitly deferred and unaffected here) is a separate question about what
happens *after* Risk/Compliance, not about how the winner was chosen in the
first place. No dependency was found requiring the two to be decided
together; they are separable, and this document does not decide either.

## 13. Observability requirements for policy

Re-confirmed, not extended: ADR-037 §12 already requires session-scan-
started/completed with expected-vs-actual counts, no-candidates, winner-
selected (`range_start`/`SessionName`/pair), tie/no-winner-despite-candidates,
incomplete-scan, selector-failure, stale-winner, downstream-rejection, and
the Gate-B-anchor-with-no-enabled-session defense-in-depth signal. ADR-031
Amendment 1 §5 requires Runtime's own audit trail to distinguish six
lifecycle categories, cross-referencing ADR-037 §12 for the full catalogue
rather than restating it. **Whatever ranking/tie policy is eventually
adopted must be recordable within this already-required signal set**: a
"tie / no-winner produced despite candidates existing" signal already exists
and is policy-agnostic (it does not need to know *which* tie rule fired to
record that one did); a "winner selected" signal already carries the
identity needed for reproducibility. No new observability requirement was
found beyond what §12/§5 already mandate — the eventual ranking/tie decision
should record its own inputs (candidate set, computed values, chosen
tolerance) as part of the existing "winner selected" / "tie" signals, not as
new categories. This document does not require logging any signal not
already named above (e.g., no requirement to log raw account/margin state).

## 14. Adversarial policy matrix

| # | Scenario | Finding |
|---|---|---|
| 1 | Two candidates, different scores | `score` alone (§4) already orders them; no new signal required |
| 2 | Exact score tie | No repository precedent for exact float equality as the tie test (§6); tolerance-band precedent exists (`score_tie_tolerance`) but is not adopted here |
| 3 | Nearly equal scores (within some small delta) | Whether this counts as "tied" depends entirely on the (unresolved) tolerance value/rule (§6) — genuinely undecidable without a policy choice |
| 4 | One candidate only | Trivially the winner under any ranking rule surveyed; no ambiguity found |
| 5 | Zero candidates | Already governed by ADR-037 §5.D/§7 (complete scan, no candidates) — no new finding; not reopened |
| 6 | Higher score but worse spread | `current_spread` is a hard gate today, not a ranking input (§4) — a qualified candidate already passed the spread gate; "worse spread" among two already-qualified candidates would require `current_spread` (needs normalization, §10) or `liquidity_score` (already normalized) as an *additional* ranking input, which is not adopted here |
| 7 | Higher score but lower liquidity | Same as #6 — `liquidity_score` is a gate, not (yet) a ranking input; using it as one would not double-count (§3), unlike `pair_safety_score`/`readiness_score` |
| 8 | FVG bonus vs. no FVG | Already fully embedded in `score` today (§3/§4) — no separate signal needed if `score` is the ranking key |
| 9 | Same pair wins London and New York independently | Already guaranteed safe by `range_start`-alone identity (§9) — no policy dependency |
| 10 | London tie, New York clear winner | Each window's completeness/selection is independent (ADR-037 §5.F, unchanged) — a tie in one window has no bearing on another; confirmed, not a new finding |
| 11 | Only one enabled session | Architecture already supports this (§8) — no ranking-policy dependency beyond what already exists for N sessions |
| 12 | More than two enabled sessions | Same as #11 — architecture-level, not a ranking-policy dependency |
| 13 | Pair ordering reversed | ADR-031 Amendment 1 §8 already requires deterministic, symbol-sorted candidate-set assembly (citing `evaluate_batch()`'s existing precedent) — a ranking rule that is a pure function of candidate values (not input order) is unaffected by assembly order regardless of which rule is chosen; this is an architecture-level guarantee already made, not something the ranking rule itself must additionally guarantee |
| 14 | Restart before selection | Governed by ADR-037 §9's persistence/fail-closed contract (unchanged) — orthogonal to ranking-policy content |
| 15 | Ranking inputs stale/missing | Not found to be possible for `score`/`confidence` specifically (produced fresh every cycle as part of the mandatory front-half pass, §5.A of ADR-037) — would only arise if a future policy chose a signal from a different, potentially-stale source; not applicable to any signal in §3's "already part of strategy qualification" row |
| 16 | Ranking calculation exception | Already covered by ADR-037 §12's "selector failure of any kind" observability requirement and §7/§12's fail-closed rule (zero winners) — no ranking-policy-specific gap found |
| 17 | Test-only pair/session policy mistaken for production configuration | Already explicitly flagged as adversarial scenario #5 in ADR-037 §15's own table ("This ADR explicitly declines to name any pair, anchor, or session count as production policy... the eventual Plan/deployment-profile decision must draw production values from an authoritative operator decision, not test fixtures") — re-confirmed, not a new finding, and directly relevant: this research's own findings (§3–§10) must not be mistaken for that authoritative decision either. **This document is Research, not that decision.** |

No scenario above was resolved by inventing a ranking weight, tie rule, or
session value — every disposition is either "already governed by settled
architecture" or "genuinely depends on an unresolved policy choice," exactly
as this task requires.

## 15. Recommended governance vehicle

**Recommendation: neither an ADR-037 amendment nor a new ADR by itself is the
smallest correct vehicle for the ranking-formula/tie-rule/session-content
decision — this is a deployment/product-policy decision, most naturally
recorded as part of the future ADR-037 implementation Plan (already named as
the next step by ADR-037 §17 item 4 and ADR-031 Amendment 1's own closing
"Important" instruction), not a separate architecture document.**

Reasoning, distinguishing the three governance levels this task's §15 names:

- **Architecture decision** (ADR-level): already fully made by ADR-037 and
  ADR-031 Amendment 1 — the *shape* of the ranking contract (pure function,
  `Optional[pair]` output, deterministic, candidate-set input) is settled.
  Nothing found in this research suggests that shape needs to change or be
  amended; no new ADR/amendment is warranted for what this research covers.
- **Trading policy** (which signal(s), what tolerance, what tie rule): this
  is exactly the kind of concrete, numeric, reviewable decision the RPI
  Plan phase (not a governance/ADR phase) exists for — analogous to how
  `config.score_tie_tolerance`'s specific value, or `orb_min_liquidity_score`'s
  specific threshold, were Plan/implementation-level decisions under their
  own already-Accepted ADRs (ADR-026, ADR-035), never separate ADRs of their
  own. A future ADR-037 implementation Plan is the correct place to propose
  and justify a specific ranking formula/weights and tie rule, subject to its
  own independent Plan review — consistent with ADR-037 §17 item 4's own
  language ("a dedicated Plan artifact... is where the ranking formula...
  would eventually be *proposed*").
- **Deployment profile** (exact enabled sessions/anchors/pairs — the "New
  York" `SessionName` mapping from §7, Gate A's eventual width): this is
  operator/deployment configuration content, not architecture or even
  Plan-level code design — it belongs in the same category ADR-036
  Amendment 1 already established for Gate A/B values themselves ("this ADR
  does not set that list's contents"; the actual values are a deployment-
  profile decision made when the narrow or broad Gate A/B path is chosen).

**Only if** a future Plan discovers that satisfying the ranking/tie
requirement genuinely requires a *new* architectural capability beyond what
ADR-037/ADR-031 Amendment 1 already authorize (for example, if Risk-owned
information turned out to be unavoidably necessary pre-Risk, which §11 found
it is not) would an ADR amendment be the correct vehicle at that later point.
No such requirement was found here.

## 16. Unresolved decisions (explicitly not made by this document)

- The exact ranking formula/weights (which signal(s) among `score`,
  `liquidity_score`, `news_score`, or others; whether `confidence` is
  included despite currently adding no discriminating power for ORB).
- The exact tie rule (reject-on-tie vs. deterministic-secondary-key vs. some
  other rule) and its exact tolerance value.
- The exact initial production session list and which `SessionName`(s)/
  anchor(s) constitute "New York" for that list.
- Gate A's eventual production width/composition (narrow vs. broad — a
  distinct ADR-036-governed decision, unaffected by this research).
- Whether `TradeReadiness.readiness_score` or Research Engine's pair-level
  historical ranking may ever be consulted by a decision-adjacent component
  without first reconciling ADR-025 Hard Rule 6 / ADR-029 Hard Rule 2's
  "advisory only" language — flagged, not resolved.
- The enabled-sessions-list configuration-ownership module (extends
  `validate_profile()`'s pattern per ADR-031 Amendment 1 §1, but the specific
  module/schema is not named).
- The stale, pre-Acceptance "Proposed" wording left in ADR-031 Amendment 1's
  own §12/footer (§1 of this document) — a documentation-only defect,
  correctable in a future administrative pass, not corrected here.

None of the above may be inferred, assumed, or silently decided by any future
work citing this document as authorization. This document identifies
evidence and dependencies only.

## 17. Explicit non-authorization (restated)

This document does not authorize, and no future work may cite it as having
authorized: implementation of the Opportunity Selection Engine or any Runtime
change; any ranking formula or weight; any tie-handling rule; any exact
production pair, anchor, session, or clock value; Gate A or Gate B
activation; legacy-strategy retirement; any modification to ADR-031,
ADR-035, ADR-036, or ADR-037; any test modification; the ADR-035 Phase 5
anchor hour/minute validation follow-up (separately gated, unauthorized,
unrelated to this research throughout).

---

*This document is a Research artifact only. It settles no policy question.
The next governance step, if this research is judged sufficient, is a
product-policy decision (most appropriately as part of a future ADR-037
implementation Plan, per §15 above) — not performed here.*
