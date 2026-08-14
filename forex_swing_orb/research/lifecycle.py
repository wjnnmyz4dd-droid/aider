"""Lifecycle fact-ingestion (Phase 9C / PR-3M) — the ONE reader that stitches the
persisted, immutable per-signal outcome fact into the closed-trade records the
existing research calculators already consume.

NON-DUPLICATIVE by design. It ingests the canonical outcome fact — the
``execution_outcome`` record written EXACTLY once per ``signal_id`` by
``manage.outcome.OutcomeReconciler`` into the shared MemoryStore — and delegates ALL
metric math to the existing single owners:

  * per-trade realized R + win/loss fact   -> manage.outcome (produced upstream)
  * expectancy / profit factor / drawdown / equity / win-loss / MAE-MFE
                                            -> research.portfolio (canonical calculators)
  * session/symbol breakdowns              -> research.reporting
  * FTMO levels                            -> compliance.contract.ftmo_levels (read-through)

It NEVER recomputes R / P&L / expectancy / drawdown, and it owns ZERO trading
authority: it reads a MemoryStore only (injected, duck-typed ``.query``); it never
places/sizes/blocks a trade, touches a broker, writes a bridge/manage instruction,
mutates PM state, or imports execution / compliance-authorization / sizing code.

Correlation key: ``signal_id`` (16-hex). Idempotent: one signal_id -> at most one
closed trade (the outcome fact is already one-per-signal; rejected / HELD / never-
closed signals have NO outcome fact and thus never appear — no phantom trades).

Facts that Session Edge does NOT persist are surfaced as None / UNAVAILABLE and are
NEVER fabricated: realized monetary P&L, MAE, MFE, commission, swap, session, and a
numeric trade score (no trade score exists in the engine today — see
docs/SESSION_EDGE_ANALYTICS_OWNERSHIP.md).
"""

from __future__ import annotations

import math
import re

from . import portfolio, reporting

# Canonical closed-trade fact kind in the shared MemoryStore (manage.outcome).
OUTCOME_KIND = "execution_outcome"

# A production signal_id is sha256[:16] (same trivial format the writer enforces in
# manage.outcome / runtime.adoption / manage.paths). The reader is kept as strict as
# the writer so a malformed / case / whitespace variant can never be counted as a
# distinct trade.
_SIGNAL_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# Realized-outcome-defining fields that MUST agree for a repeated signal_id; any
# disagreement is a genuine terminal-fact conflict (fail closed, never keep-first).
_OUTCOME_IDENTITY_FIELDS = ("status", "won", "r_multiple", "direction", "symbol",
                            "entry", "initial_stop", "weighted_close", "closed_volume")


def _valid_sid(sid):
    """A well-formed production signal_id (sha256[:16]); anything else is ignored."""
    return isinstance(sid, str) and bool(_SIGNAL_ID_RE.match(sid))


def _finite_num(x):
    """Finite real number (rejects bool / NaN / Inf / non-numeric)."""
    return (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))


def _outcomes_conflict(a, b):
    """True iff two normalized outcome records for the same signal_id disagree on
    any realized-outcome-defining field (a real conflict, not a benign duplicate)."""
    return any(a.get(k) != b.get(k) for k in _OUTCOME_IDENTITY_FIELDS)

# Provenance classes (§10 / K): never present an estimate as broker truth.
REALIZED_BROKER_FACT = "REALIZED_BROKER_FACT"   # observed from MT5 (deal history / fills)
DERIVED_METRIC = "DERIVED_METRIC"               # computed from immutable facts by a single owner
UNAVAILABLE = "UNAVAILABLE"                      # not persisted anywhere -> never fabricated

FACT_AVAILABILITY = {
    # broker facts captured in the outcome record
    "symbol": REALIZED_BROKER_FACT, "direction": REALIZED_BROKER_FACT,
    "entry": REALIZED_BROKER_FACT, "weighted_close": REALIZED_BROKER_FACT,
    "closed_volume": REALIZED_BROKER_FACT,
    # derived by a single owner (manage.outcome / research.portfolio)
    "r_multiple": DERIVED_METRIC, "won": DERIVED_METRIC,
    "expectancy": DERIVED_METRIC, "profit_factor": DERIVED_METRIC,
    "max_drawdown": DERIVED_METRIC, "win_rate": DERIVED_METRIC,
    # NOT persisted anywhere in Session Edge -> UNAVAILABLE (never fabricated)
    "realized_pnl": UNAVAILABLE, "mae": UNAVAILABLE, "mfe": UNAVAILABLE,
    "commission": UNAVAILABLE, "swap": UNAVAILABLE,
    "session": UNAVAILABLE,           # not on the outcome fact (audit-join not ingested here)
    "trade_score": UNAVAILABLE,       # no numeric trade score exists in the engine
}

# --------------------------------------------------------------------------- #
# Score cohorts — evidence readiness for FUTURE score-based sizing research (G/H).
# A numeric trade score does NOT exist in Session Edge today (the frozen engine emits
# binary qualification + a constant confidence=1.0). So every ingested trade currently
# classifies UNAVAILABLE and NO score-based sizing is implemented here. If a score fact
# is later added upstream, cohort_of buckets it; sub-70 is ALWAYS separated and never
# mixed into a qualifying cohort. PR-3J remains the sole lot/volume authority.
# --------------------------------------------------------------------------- #
SCORE_MIN_QUALIFYING = 70
SCORE_COHORTS = ("70-74", "75-79", "80-84", "85-89", "90-94", "95-100")
SCORE_BELOW_MIN = "BELOW_70"
SCORE_UNAVAILABLE = "UNAVAILABLE"


def cohort_of(score):
    """Map a numeric score to its cohort label. Sub-70 -> BELOW_70 (kept separate);
    a missing / non-numeric / out-of-range score -> UNAVAILABLE (never guessed)."""
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return SCORE_UNAVAILABLE
    if not math.isfinite(score) or score < SCORE_MIN_QUALIFYING or score > 100:
        return SCORE_BELOW_MIN if (math.isfinite(score) and score < SCORE_MIN_QUALIFYING) \
            else SCORE_UNAVAILABLE
    lo = min(int((score - SCORE_MIN_QUALIFYING) // 5) * 5 + SCORE_MIN_QUALIFYING, 95)
    hi = 100 if lo == 95 else lo + 4
    return f"{lo}-{hi}"


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #
def _trade_from_outcome(c):
    """Normalize one execution_outcome content dict into a research trade record.
    Unpersisted facts are explicit None (UNAVAILABLE) — never fabricated."""
    return {
        "signal_id": c.get("signal_id"),
        "symbol": c.get("symbol"),
        "direction": c.get("direction"),
        "status": c.get("status"),               # CLOSED | R_UNDEFINED
        "won": c.get("won"),
        "taken": c.get("taken"),
        "r_multiple": c.get("r_multiple"),       # None when R_UNDEFINED (zero-risk edge)
        "entry": c.get("entry"),
        "initial_stop": c.get("initial_stop"),
        "weighted_close": c.get("weighted_close"),
        "closed_volume": c.get("closed_volume"),
        "realized_r_source": c.get("realized_r_source"),
        "source_kind": OUTCOME_KIND,
        # UNAVAILABLE facts (surfaced, never fabricated)
        "realized_pnl": None, "mae": None, "mfe": None, "session": None,
        "trade_score": None,
    }


def load_closed_trades(memory, *, limit=1_000_000):
    """Read the canonical per-signal ``execution_outcome`` facts from the shared
    MemoryStore and return normalized closed-trade dicts, deduped by signal_id and in
    deterministic signal_id order. Only TAKEN (executed) signals become trades, so a
    rejected / HELD / never-reconciled signal never appears. Read-only.

    Fails closed on bad terminal facts (the writer prevents these on the canonical
    path; this is defense-in-depth against a non-canonical writer / store damage):

      * a malformed signal_id (not sha256[:16]) is ignored (F2);
      * a present-but-non-finite ``r_multiple`` (string / bool / NaN / Inf) is a
        corrupt record and is dropped — ``None`` (R_UNDEFINED, zero-risk edge) is
        preserved, never fabricated to 0 (F4);
      * two records for one signal_id that DISAGREE on any realized-outcome-defining
        field are a conflict: the signal_id is QUARANTINED and yields NO trade,
        rather than silently keeping whichever was written first (F1)."""
    rows = memory.query(kind=OUTCOME_KIND, limit=limit)
    by_sid = {}
    conflicts = set()
    for row in rows:
        content = (row.get("content") if isinstance(row, dict) else None) or {}
        sid = content.get("signal_id")
        if not _valid_sid(sid):                   # F2: reject malformed signal_id
            continue
        if content.get("taken") is not True:
            continue                              # never count a non-executed signal as a trade
        rm = content.get("r_multiple")
        if rm is not None and not _finite_num(rm):
            continue                              # F4: corrupt R -> drop (None is kept below)
        trade = _trade_from_outcome(content)
        if sid in by_sid:
            if _outcomes_conflict(by_sid[sid], trade):
                conflicts.add(sid)                # F1: divergent terminal facts -> quarantine
            continue                              # benign duplicate -> dedup (identical content)
        by_sid[sid] = trade
    # fail closed: a signal_id with contradictory outcomes contributes NO trade.
    return [by_sid[s] for s in sorted(by_sid) if s not in conflicts]


def cohort_breakdown(trades):
    """Bucket trades by score cohort and summarize each with the CANONICAL
    portfolio.summary (no metric recomputed here). With no score present upstream,
    all trades land in UNAVAILABLE — proving the evidence layer is READY without
    fabricating a score. sub-70 (if a score ever exists) is a separate bucket."""
    buckets = {}
    for t in trades:
        buckets.setdefault(cohort_of(t.get("trade_score")), []).append(t)
    return {c: portfolio.summary(ts) for c, ts in sorted(buckets.items())}


def quality_dataset(instructions, memory=None):
    """Observational research dataset joining per-signal setup-quality facts (extracted
    purely from the immutable authorized instructions by research.quality_facts) with
    realized outcome R (from the canonical execution_outcome fact, if a MemoryStore is
    given), keyed by signal_id. Measurement only — recomputes no metric, owns no
    authority. Deterministic, idempotent (deduped by signal_id, sorted), and immutable
    (a pure function of immutable instructions). ``outcome_r`` / ``closed`` /
    ``trade_score`` are UNAVAILABLE until a closed outcome / score exists; a written-but-
    unexecuted signal is a candidate observation, NOT a closed trade (never phantom P&L)."""
    from . import quality_facts
    outcome_r = {}
    if memory is not None:
        for t in load_closed_trades(memory):
            outcome_r[t["signal_id"]] = t.get("r_multiple")
    rows = {}
    for instr in instructions:
        qf = quality_facts.extract(instr)
        sid = qf.get("signal_id") if isinstance(qf, dict) else None
        if not _valid_sid(sid) or sid in rows:
            continue                                  # reject malformed sid; dedup one set per signal_id
        qf = dict(qf)
        qf["outcome_r"] = outcome_r.get(sid)          # None until the trade closes
        qf["closed"] = sid in outcome_r
        rows[sid] = qf
    return [rows[s] for s in sorted(rows)]


def lifecycle_report(memory):
    """One observational report composed ENTIRELY from the canonical calculators —
    this module recomputes nothing. Distinguishes realized broker facts / derived
    metrics / unavailable facts, and reuses research.portfolio + research.reporting."""
    trades = load_closed_trades(memory)
    return {
        "trade_count": len(trades),
        "overall": portfolio.summary(trades),          # canonical portfolio math
        "by_symbol": reporting.pair_performance(trades),  # canonical breakdown
        "by_score_cohort": cohort_breakdown(trades),
        "fact_availability": dict(FACT_AVAILABILITY),
        "score_status": SCORE_UNAVAILABLE,             # no trade score exists yet
        "source_kind": OUTCOME_KIND,
    }
