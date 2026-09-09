# Session Edge — Trade-Score Authority: SPECIFICATION REQUIRED (PR-3N)

Status: **BLOCKED — TRADE-SCORE AUTHORITY SPECIFICATION REQUIRED.**

PR-3M's score-cohort analytics (`research/lifecycle.py`, bands 70–74 … 95–100 +
BELOW_70 + UNAVAILABLE) are ready, but there is **no authoritative numeric trade
score** anywhere in the Session Edge decision path to persist. PR-3N is an
observational-provenance PR only; it is explicitly **not** authorized to invent a
score, convert pass/fail gates into points, reinterpret unrelated confidence/evidence
values, or adopt a 70 threshold from conversation. No production score code was added.

## Finding: no authoritative numeric trade score exists (source + spec)

- **Spec is explicit** — `docs/FOREX_SWING_ORB_SPEC.md` §8.3: *"v1 is a deterministic,
  rule-based qualifier: a setup either passes every gate or is not emitted. There is
  **no graded score** in v1; the field is emitted as fixed `confidence = 1.0` … A
  graded model is deferred (schema/version change)."*
- The frozen engine emits `confidence = 1.0` as a **fixed constant** (`run_dir/code/
  signal_engine.py`), never a graded value — a pass/fail artifact, not a score.
- `rr_planned` / `min_rr = 2.0` is a **hard reward:risk GATE** (pass/fail), not a
  graded score; converting it to points is forbidden here.
- The instruction schema (`bridge/contract.py REQUIRED_INSTRUCTION_FIELDS`) and the
  compliance candidate carry **no score field**.
- Sizing (`compliance/sizing.py`, PR-3J), the execution consumer, the MQL5 EA, and the
  compliance gates have **zero** score reference or threshold.

## Score-concept inventory + classification

| Concept | Location | Class |
|---|---|---|
| `confidence = 1.0` (fixed) | `run_dir/code/signal_engine.py` | NOT-A-SCORE (spec §8.3: fixed pass/fail qualifier) |
| `rr_planned` / `min_rr` | `signal_engine.py` | HARD GATE (pass/fail), not graded |
| agent `confidence` (0.0–1.0), `agreement_score` | `agents/` (shadow/advisory, LIVE_AUTHORITY=False) | UNRELATED (observe-only; never writes instruction/bridge) |
| `rank` | `position/contract.py` | UNRELATED (manage priority order) |
| `trade_score` (always None/UNAVAILABLE) | `research/lifecycle.py` (PR-3M) | ANALYTICS PLACEHOLDER (no producer) |
| "Phantom score/decision (scorer.py/scanner.py)" | `docs/VIBE_TRADING_PHASE0_AUDIT.md` | DOCUMENTATION-ONLY (future/optional; not implemented) |

**No AUTHORITATIVE numeric trade score exists.** Therefore there is nothing to persist
as an authorization-time score fact, and the score-cohort layer correctly remains
UNAVAILABLE.

## Canonical ownership map (unchanged; single owner each)

| Responsibility | Single owner |
|---|---|
| Trade score | **NONE — specification required** |
| Score cohorts | `research/lifecycle.py::cohort_of` (classifier only; no score producer) |
| Entry eligibility | producer `_session_trade_eligible` + M12 profiles |
| News authorization | `compliance/news.py` |
| Session eligibility | `session/model.py` + profiles |
| risk_fraction policy | strategy config / compliance (declared) |
| Monetary sizing | `compliance/sizing.py` (PR-3J) |
| Volume / lot size | `compliance/sizing.py` (PR-3J) — sole authority |
| Price geometry | `position/geometry.py` (H6) |
| Outcome R | `manage/outcome.py` |
| Portfolio metrics | `research/portfolio.py` |

## Decisions required before a trade-score authority can be implemented

| # | Decision | Options / notes |
|---|---|---|
| 1 | **Score range** | 0–100 (matches the existing cohort bands) or another range. If not 0–100, the cohort bands must be re-specified. |
| 2 | **Score components** | Which existing strategy facts contribute (e.g. `rr_planned`, trend agreement `trend_d1`/`trend_h4`, retest quality, ATR/structure) — each must be an existing engine fact, not a new market computation. |
| 3 | **Weights** | Exact weight per component; must be deterministic and versioned. |
| 4 | **Hard gates vs score** | Which conditions remain ABSOLUTE pass/fail and may NEVER be compensated by a high score (news lockout, FTMO/account limits, session eligibility, min RR, spread/slippage, data freshness, geometry). |
| 5 | **Minimum threshold** | Whether 70 is formally adopted as the minimum qualifying score, and whether it becomes an entry gate (a separate policy PR, not measurement). |
| 6 | **Score timing** | Exactly when the score freezes (at candidate generation, before compliance) so it is immutable for the signal_id. |
| 7 | **Session behavior** | One scoring model for all sessions, or session-specific. |
| 8 | **Symbol behavior** | One scoring model for all FX pairs, or per-pair. |
| 9 | **Missing data** | Fail closed (no trade) vs UNAVAILABLE (trade allowed, score absent) when a component input is missing. |
| 10 | **Versioning** | `score_model_version` required in the persisted fact so historical cohorts stay comparable across model changes. |

## Boundaries reaffirmed (unchanged by this PR)

- **No score-based entry threshold** was implemented (measurement ≠ policy).
- **No score-based lot sizing** was implemented. PR-3J (`compliance/sizing.py`
  `allowable_volume`) remains the sole volume/lot-size authority.
- The only permitted FUTURE structure, once a score authority is explicit and verified:
  `score → evidence-backed risk-tier policy → permitted risk_fraction/monetary budget
  → PR-3J sizing → authoritative volume → compliance recomputation → EA executes verbatim`.
- Missing score stays **UNAVAILABLE** — never substituted with 0 / 70 / 100 / a default
  / an average / a previous score.
