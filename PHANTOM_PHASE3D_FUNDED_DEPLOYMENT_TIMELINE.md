# Phase 3D — Recommended Timeline Before Funded Deployment

This is a recommendation, not a guarantee — actual timing depends on how
quickly the demo period naturally exercises the scenarios below and on
closing Gap #1 (see Remaining Known Gaps).

## Minimum recommended demo period: 2-4 weeks

Reasoning: a shorter period is unlikely to naturally produce every
condition the fail-closed matrix covers (a real broker feed hiccup, a
weekend gap, a genuine qualifying strategy signal reaching Risk/Compliance
end-to-end). This phase validated the mechanisms in a sandbox; the demo
period's job is to validate the same mechanisms against real, unpredictable
market conditions.

## What must be true before funded consideration

1. **Gap #1 closed** — day-start/peak/lock state genuinely persisted
   across cycles and restarts, so Compliance Engine's daily-loss/drawdown
   gates enforce real prop-firm rules. This requires its own explicitly-
   scoped ADR amendment and implementation; do not fund an account before
   this is done, regardless of how clean the demo period looks.
2. **At least one real qualifying trade signal observed end-to-end**
   through Strategy → Risk → Compliance → Bridge during the demo period,
   confirmed via `health_check.py` and log review, with a decision that
   matches expectations.
3. **Zero unintended trades** across the full demo period — the fail-
   closed matrix validated in this phase (stale feed, duplicate/out-of-
   order bars, warmup incomplete, EA disconnect) must continue to produce
   zero trade decisions when triggered naturally, not just under
   simulated conditions.
4. **`health_check.py` reviewed daily for the full period** with no
   unexplained `FAILED` status or unexplained queue growth.
5. **The user has personally verified** the Final Deployment Checklist
   and Final Operator Checklist items on their own MT5 installation, not
   relying solely on this phase's sandbox simulation.

## After those conditions are met

Consider a small, closely-monitored funded position size first (well
below the account's actual risk limits) for an additional short period
before scaling to full intended size — this phase's validation covers the
mechanism, not statistical edge, which remains the Quant Validation
Engineer's domain and is out of this phase's scope entirely.
