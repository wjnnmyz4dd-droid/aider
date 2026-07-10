# Technical Specification — Market Intelligence Engine

Specification only. Cross-references `PHANTOM_FINAL_ARCHITECTURE.md`
and `PHANTOM_IMPLEMENTATION_ROADMAP.md` §3.2 and Phase 3b.

## 1. Purpose

The single news/session/liquidity-awareness authority: gives every
enabled pair its own News Score, Market Impact Score, and Pair Safety
Score, and exposes one deterministic, mandatory entry-gate query that
hard-blocks new entries around high-impact/critical events — advisory
in its scoring, but factual and mandatory in its gating.

## 2. Responsibilities

- Ingest an economic calendar and news feed, scoped to enabled pairs.
- Classify events: high-impact, central bank, interest-rate decisions,
  CPI, PPI, GDP, NFP, employment, PMI, speeches, currency-peg/
  exchange-policy announcements, and holiday schedules.
- Score session quality, liquidity quality, spread quality, and produce
  a short-horizon volatility forecast, per pair.
- Maintain news blackout windows around high-impact/critical events.
- Combine the above into `NewsScore`, `MarketImpactScore`, and
  `PairSafetyScore` per pair.
- Expose `get_entry_gate(pair, now)` as a hard, mandatory precondition
  distinct from the advisory scores.

## 3. Public interfaces

```
intelligence_engine.get_pair_intelligence(pair: Pair, now: Clock) -> PairIntelligence
intelligence_engine.get_entry_gate(pair: Pair, now: Clock) -> EntryGateDecision
```

Two distinct calls, deliberately: `get_pair_intelligence`'s scores are
inputs to Risk Engine's sizing; `get_entry_gate`'s decision is a
mandatory precondition Strategy Engine must check before it may emit a
`TradeIdea` at all. Conflating them into one call risks a caller
treating the gate as just another score to weigh rather than a hard
stop.

## 4. Inputs

- Enabled-pair list, blackout-window widths, per-event-type impact
  weighting (`config.py`).
- Economic calendar / news feed data, via `calendar_source.py` — no
  live provider is wired in this phase (interfaces only, per this
  task's explicit scope).
- A `Clock` for evaluation timestamps.

## 5. Outputs

`PairIntelligence` (`NewsScore`, `MarketImpactScore`, `PairSafetyScore`,
session/liquidity/spread quality, volatility forecast — all per pair)
and `EntryGateDecision` (`ALLOWED` / `BLOCKED_NEWS_BLACKOUT` /
`BLOCKED_HOLIDAY` / `BLOCKED_PEG_POLICY_EVENT`).

## 6. Internal data models

| Model | Shape |
|---|---|
| `EconomicEvent` | kind (CPI/PPI/GDP/NFP/employment/PMI/rate-decision/speech/central-bank/peg-policy), affected currency/currencies, scheduled time, impact classification, actual/expected/prior values where applicable |
| `NewsScore` | 0–100, per pair, reflecting general news-environment favorability |
| `MarketImpactScore` | 0–100, per pair, reflecting the magnitude of upcoming/recent event impact specifically (distinct from the general news score) |
| `PairSafetyScore` | 0–100, the aggregate of News Score, Market Impact Score, session/liquidity/spread quality, and volatility forecast |
| `EntryGateDecision` | enum: `ALLOWED`, `BLOCKED_NEWS_BLACKOUT`, `BLOCKED_HOLIDAY`, `BLOCKED_PEG_POLICY_EVENT` |
| `PairIntelligence` | `(pair, news_score, market_impact_score, pair_safety_score, session_quality, liquidity_quality, spread_quality, volatility_forecast, evaluated_at)` |

## 7. Decision authority

Advisory in its scores (never chooses a trade, never sizes), but the
**sole** authority for whether new entries are currently permitted on
a pair from a news/calendar/policy standpoint — `get_entry_gate` is
mandatory and non-overridable by Strategy Engine, Risk Engine, or
Compliance Engine; none of those may substitute their own judgment for
a `BLOCKED_*` result.

## 8. Dependencies

`phantom/shared/` only, plus its own calendar/news ingestion. No
dependency on Evidence Engine, Strategy Engine, or PhantomBridgeEA.

## 9. Explicit non-responsibilities

- Never evaluates price structure, regime, or indicators — that is
  Evidence Engine's domain (architecture freeze §13 item 2: this
  component answers "is it safe to trade right now," not "what does
  price structure look like").
- Never selects a strategy or produces a `TradeIdea`.
- Never sizes a position.
- Never integrates a live news/calendar provider in this phase —
  interfaces and deterministic classification logic only;
  `calendar_source.py` in this phase operates against fixture/
  configured data, not a live feed.
- Never lets its advisory scores substitute for the mandatory
  `get_entry_gate` check, or vice versa.

## 10. Test plan

- Unit tests per classification/quality-scoring module against fixture
  calendars (CPI/PPI/GDP/NFP/employment/PMI/rate-decision/speech/
  central-bank/peg-policy/holiday fixtures each individually verified).
- Entry-gate fixture suite: every fixture event the spec below names
  as high-impact/critical produces the correct `BLOCKED_*` value for
  the correct pair(s) and time window; every non-qualifying fixture
  produces `ALLOWED`.
- Boundary test: no other package under `phantom/` parses calendar/news
  data independently (enforces "no duplicate news processing").
- Score-independence test: `PairSafetyScore` changing must never change
  `get_entry_gate`'s result for a case that doesn't independently meet
  a `BLOCKED_*` condition — the two outputs must not be entangled.

## 11. Performance requirements

`get_entry_gate` must be cheap enough to call as a precondition on
every Strategy Engine evaluation cycle without becoming the bottleneck
(target: sub-10ms per pair against pre-loaded fixture/calendar data,
validated during implementation).

## 12. Failure modes

| Failure | Expected behavior |
|---|---|
| Calendar/news source unavailable | Fail closed: `get_entry_gate` returns a `BLOCKED_*` state (never silently `ALLOWED`) when the engine cannot positively confirm no qualifying event is active — matching the Charter's fail-closed-by-default rule. |
| Malformed/partial event data | Logged and excluded from scoring for that event only; does not crash the batch evaluation of other pairs. |

## 13. Security considerations

No live provider integration in this phase, so no external credential
surface yet; when a live provider is added in a future, separately-
approved phase, its credentials belong in `config.py`'s secret
convention, never hardcoded or logged.

## 14. Logging requirements

`logging_sink.py` logs every `get_entry_gate` call and result, and
every `PairIntelligence` evaluation. `metrics.py` tracks blocked-vs-
allowed counts by block reason, per-event-type classification counts,
and evaluation latency.

---

## Market Intelligence Framework (detailed)

### Pair-specific news scoring

Every enabled pair receives its own `NewsScore` and
`MarketImpactScore`, computed independently — no cross-pair sharing
even for pairs sharing a currency (e.g. EURUSD and EURGBP both
reference EUR events, but each pair's score is computed from its own
currency-pair exposure, not copied from the other). `NewsScore`
reflects the general news environment (how much scheduled/unscheduled
news activity surrounds this pair's two currencies over the relevant
horizon); `MarketImpactScore` reflects the magnitude of the nearest
upcoming or most recent high-impact event specifically. Keeping them
separate lets Risk Engine's scaling distinguish "generally newsy
period" from "a specific high-magnitude event is imminent."

### Pair Safety Score

The aggregate of `NewsScore`, `MarketImpactScore`, session quality,
liquidity quality, spread quality, and the volatility forecast, into
one 0–100 figure per pair, computed by `pair_safety_score.py` and
consumed by Risk Engine's `confidence_scaling.py` as a scaling input
alongside Evidence Engine's confidence score. `PairSafetyScore` is
advisory (it scales size, it does not itself block), which is why it
is architecturally distinct from `get_entry_gate`'s hard block.

### London and New York session preference

`session_quality.py` weights the London and New York sessions (and
their overlap) as the highest-quality trading windows by default
configuration — these are the sessions with the deepest liquidity and
most reliable price discovery for the majors/crosses this system
targets. The Asian session is not excluded, but scores lower by
default for pairs whose liquidity is primarily London/New York-driven;
a pair with genuine Asian-session liquidity (e.g. AUDJPY, NZDJPY) may
be configured with its own session-quality weighting rather than
inheriting the default — this is a per-pair configuration point in
`config.py`, not a hardcoded global rule.

### High-impact news blackout rules

`news_blackout.py` computes a blackout window around every event
`event_classifier.py` marks high-impact or critical (central bank
decisions, interest-rate decisions, CPI, PPI, GDP, NFP, and — per this
task's expanded scope — Employment and PMI releases, plus scheduled
speeches from classified central-bank speakers). The window has a
configurable pre-event and post-event width (both required in
`config.py`, no default silently assumed here); while the current time
falls inside that window for a pair's affected currency, `get_entry_gate`
returns `BLOCKED_NEWS_BLACKOUT` for that pair, unconditionally.

### Currency-policy/peg event handling

Currency-peg or exchange-policy events (a central bank defending or
adjusting a peg, a surprise policy announcement, capital-control
changes) are handled on a **separate path** from scheduled-calendar
blackouts, because they are frequently unscheduled and materially
higher-severity than a routine data release: `peg_policy_protection.py`
classifies these independently of `event_classifier.py`'s
scheduled-calendar path, and a detected peg/policy event produces
`BLOCKED_PEG_POLICY_EVENT`, which — unlike a scheduled blackout's
fixed pre/post window — remains active until explicitly cleared
(either by a configured cooldown period appropriate to that event
class, or by an operator action), since an unscheduled policy shift
does not resolve on the same predictable clock a scheduled release
does. This distinction (fixed-window scheduled blackout vs.
held-until-cleared policy block) is a deliberate design decision,
stated here so implementation does not collapse the two into one
mechanism.
