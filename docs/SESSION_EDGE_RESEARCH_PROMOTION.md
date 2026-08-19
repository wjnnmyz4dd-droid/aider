# Session Edge — Research → Production Promotion Process (design; NOT activated)

This document defines the **evidence gate** that any future strategy/config change must
pass before it can reach production, and restates the architectural boundary that keeps
quantitative research a **research and validation layer** rather than a parallel trading
authority. Nothing here is activated by this PR: there is no promotion automation, no
live score, and no quality→risk coupling. It is the standard every future change is held
to.

## 1. Architectural boundary (enforced by tests)

Research is downstream evidence, never upstream authority. The canonical live owners are
unchanged and remain the ONLY authorities:

| Concern | Sole owner |
|---|---|
| direction / entry / SL / TP | frozen strategy engine (`producer.strategy_adapter` load) |
| session eligibility | `session` model / `runtime.config` |
| authorization / veto | `compliance` |
| hard account limits | FTMO controls in `compliance` |
| daily-loss anchor | `live.providers.DailyAnchorTracker` (single reconstructor) |
| live lot sizing | `compliance.sizing.allowable_volume` (PR-3J) |
| execution | MT5 execution-only EA |
| post-entry management | `position` / `manage` |
| realized-result truth | `manage.outcome.OutcomeReconciler` |

**Forbidden back-edge (test-enforced, `research/tests/test_research_boundary_ae.py`):**
no production trading package imports `research`; production never reads a research
artifact from disk; no `research/` module places/vetoes a trade, sizes a lot, calls
`allowable_volume(...)`, writes `risk_fraction`/volume, reaches the network, or imports
Phantom. A research file appearing on disk changes production behaviour in **no** way;
deleting `research/` changes production behaviour in no way.

**Allowed flow:** production → research (immutable evidence: instructions, the
`execution_outcome` fact, bridge/EA logs) and research reuse of single owners for
read-only calculation (e.g. `compliance.contract.ftmo_levels`, the frozen engine load).

## 2. The promotion gate (must ALL pass; none is automatic)

A research finding earns a production change only through an explicit, versioned,
code-reviewed edit — never by silently mutating a parameter. Required, in order:

1. **Hypothesis** — a single, pre-registered question (avoid post-hoc narratives).
2. **Sufficient sample** — realized closed trades meet the sample-size discipline
   (`research.calibration`: `<30` INSUFFICIENT, `30–199` EXPLORATORY, `≥200`
   CALIBRATION-CANDIDATE). A CALIBRATION-CANDIDATE is *not* automatically production-ready.
3. **Chronological validation** — train → validate → test or expanding walk-forward;
   never shuffled; future never trains the past; the test window is untouched until the end.
4. **Robustness** — the effect survives neighboring thresholds / adjacent buckets /
   nearby windows; narrow parameter cliffs are flagged as overfit risk.
5. **Independent out-of-sample test** — confirmed on data not used to form the hypothesis.
6. **Uncertainty + multiple-testing** — report N, confidence/bootstrap intervals, effect
   size, and the number of hypotheses tested (multiple-testing risk disclosed).
7. **Documented decision** — the A/B/C/D decision (`research.calibration.decide`) plus a
   written rationale and full provenance (dataset hash, strategy version, commit,
   windows, sessions, symbols — see `research.report_suite` provenance).
8. **Explicitly versioned change** — a normal code edit bumping the strategy/config
   version, through standard code review + the full test suite.
9. **Production** — only after all of the above.

## 3. Reproducibility (Section AC)

Every research report carries the metadata to reproduce it exactly: dataset content hash,
strategy version, code commit, date range, sessions, symbols, sample count, calibration/
test windows, seed, and injected timestamp. Same inputs → same output (deterministic; no
wall clock, randomness only via an explicit seed). See `research.report_suite.build`.

## 4. 0–100 quality score — disposition

**Not implemented as live authority; research-only.** A future interpretable 0–100
setup-quality score may be designed ONLY after the dataset supports it: enough samples,
independent + non-redundant features, stable effects across sessions/symbols/time,
out-of-sample calibration, monotonic score↔outcome where expected, no lookahead, no
leakage. The `70 = pass` idea is a **future product hypothesis**, not a rule. There is no
live score and **no 70 gate** in production (test-enforced). See
`docs/SESSION_EDGE_SCORE_MODEL_DESIGN_REQUIRED.md`.

## 5. Quality → risk coupling — disposition

**Not implemented; would modify PR-3J and must go through the gate above.** This PR does
not change risk per trade, `allowable_volume`, compliance thresholds, or scale volume by
any score/confidence factor (test-enforced). Research may only produce *evidence* that
could later support or reject such a change; it can never apply it.

## 6. Current data status

As of this PR the realized-outcome dataset in the research environment is **empty** (no
live/DEMO trading history is present). Accordingly every realized-data report degrades to
an explicit `NO_REALIZED_DATASET` / `INSUFFICIENT` / `UNAVAILABLE` status and **no edge
conclusion is drawn**. The measurement infrastructure is in place; conclusions await real
DEMO trade history captured by `manage.outcome` over time.
