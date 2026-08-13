# Session Edge — Weekend Policy (canonical contract)

Status: **AUTHORITATIVE** (M13 closed by PR-3K.1). FOREX-only, DEMO-only.

Session Edge does **not** use a fixed global Sunday reopening time. Following the
weekend, new-entry eligibility is restored only through the ordinary session,
data-freshness, strategy, compliance, risk, news, execution-health, and
broker-validity gates. Friday new-entry cutoffs remain session-specific under M12.
Existing positions remain subject to the independent Friday 20:00 UTC
weekend-flatten policy.

This document makes the weekend contract explicit and records the single owner of
each responsibility. It introduces **no new runtime authority**: every rule below is
already enforced by an existing, independently-justified mechanism. No component may
infer one policy from another — the three policies below are separate authorities.

---

## Three separate policies (no cross-inference)

### 1. ENTRY POLICY — who may open a NEW position

Owner: **M12 per-session Friday no-new-entry cutoff** (`session/profiles.py`
`SessionProfile.is_friday_no_new_entry` / `friday_no_new_entry_local_hour`) enforced
in the producer entry path (`producer/runner.py` `_session_trade_eligible` →
`RunnerReason.FRIDAY_NO_NEW_ENTRY`).

- The cutoff is **session-local and DST-aware** (each session's own IANA clock),
  derived per profile as `strategy_entry_end_local_hour - 1`:

  | Session   | Friday no-new-entry cutoff (local) |
  |-----------|-------------------------------------|
  | SYDNEY    | 19:00 |
  | TOKYO     | 21:00 |
  | LONDON    | 20:00 |
  | NEW_YORK  | 20:00 |

- **At or after** the cutoff on a Friday (`local.weekday() == 4 and local.hour >=
  cutoff`), **no new entry** may be authorized. The boundary is inclusive at the
  cutoff hour.
- There is **no separate global Friday entry clock**. The global
  `friday_close_policy` (`session/model.py`) remains `None` (disabled) unless an
  independently-justified requirement supplies a value via configuration. The
  example values `1200` / `1320` that appear in `# e.g.` comments and test fixtures
  are **not** production policy and must never become defaults.
- After the weekend, entry eligibility is **restored only** when the ordinary
  authoritative gates independently pass: valid active session; fresh & sufficient
  market data; valid OR/session construction; strategy qualification; minimum
  trade-score threshold; news authorization; account/compliance/FTMO/risk
  authorization; bridge/execution health; valid broker metadata & price geometry;
  spread/slippage and every other existing entry gate. There is **no artificial
  Sunday unlock time**: `sunday_open_policy` remains `None`.

### 2. POSITION-MANAGEMENT POLICY — what happens to OPEN positions over the weekend

Owner: **Position Manager weekend flatten** (`position/contract.py`
`weekend_policy = FLATTEN`, `weekend_cutoff_dow = 4` (Friday), `weekend_cutoff_hour_utc
= 20`) enforced in `ea_mt5/position_manager.py` `_weekend_due` →
`PMReason.WEEKEND_EXIT`.

- Open positions are protectively closed at/after **Friday 20:00 UTC** (fixed UTC,
  DST-immune by construction; and any day after Friday). This is the spec's
  `friday_close_utc` ("no position held over the weekend").
- This is a **management** authority, entirely independent of the entry policy.
  Existing positions **continue to be managed** (reconcile, break-even, profit-lock,
  structure-trail, protective exits) regardless of whether *new* entries are
  currently weekend-ineligible. Blocking new entries never disables management.
- The weekend flatten sits above break-even/lock/trail in the precedence order, so a
  protective exit is never weakened by a management rule.

### 3. DATA-FRESHNESS POLICY — what data may be acted upon

Owner: **market-data validation** (`producer/providers.py` `validate_bars`) and the
frozen engine's temporal-gap handling.

- Weekend closure / a stale or missing feed **fails closed**: the latest completed
  bar older than its per-timeframe freshness bound → `R_DATA_STALE`; a
  non-continuous series → `R_DATA_GAP` (legitimate Friday→Sunday/Monday weekend gaps
  are the only permitted large gap, and only when the feed is otherwise fresh).
- Weekend closure or stale market data must **never** fabricate an opening range,
  breakout, retest, trend confirmation, or trade opportunity. A weekend data gap is
  never silently incorporated into an OR as if it were continuous market data.

---

## Friday / Sunday / DST behavior (summary)

- **Friday:** new entries blocked at/after each session's local M12 cutoff
  (inclusive). Open positions flattened at/after Friday 20:00 UTC by the PM.
- **Saturday/Sunday:** the FX feed is closed, so data-freshness fails closed — no OR
  is constructed and no entry is authorized. There is no clock-based Sunday unlock.
- **Reopening:** whenever the feed is fresh again and a session is active, entry
  proceeds only if every ordinary gate independently passes — the same path as any
  weekday. No special "weekend just ended" state exists or is needed.
- **DST:** the M12 entry cutoff follows each session's named IANA timezone
  automatically (so the UTC instant of the cutoff shifts across DST); the PM weekend
  flatten is fixed UTC and DST-immune. These are deliberately different because they
  are different authorities.

## `None` defaults are not fail-open

`friday_close_policy = None` and `sunday_open_policy = None` do **not** create a
fail-open hole: Friday entry safety is provided by the enforced M12 per-session
cutoff, weekend position safety by the PM Friday-20:00-UTC flatten, and weekend data
safety by the data-freshness authority. The global session-model guard is an optional
extra layer that is intentionally disabled for lack of an authoritative value.

## Single-owner map (no duplicate authority)

| Responsibility                | Single owner |
|-------------------------------|--------------|
| Friday new-entry cutoff       | M12 session profiles + producer eligibility |
| Weekend position flatten      | Position Manager (`_weekend_due`) |
| Market-data freshness         | `validate_bars` / engine temporal-gap |
| Session eligibility           | session model / profiles |
| News authorization            | compliance / news gate |
| Monetary sizing / risk        | PR-3J sizing + compliance risk gate |
| Bridge health                 | H5 bridge observation |
| Producer writer authority     | F-3 single-instance lock |

No responsibility above has a second owner, and no component infers one policy from
another.
